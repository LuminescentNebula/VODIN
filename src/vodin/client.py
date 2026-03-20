from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

from .config import AppConfig
from .network import find_interface_by_name, find_interface_by_ip
from .storage import JsonStore

logger = logging.getLogger(__name__)

def _parse_nmcli_options(output: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        _, value = line.split(":", 1)
        if "=" not in value:
            continue
        key, raw = value.split("=", 1)
        options[key.strip().lower()] = raw.strip()
    return options


def _detect_linux_lease_expiration_epoch(interface_name: str) -> int | None:
    try:
        completed = subprocess.run(
            ["nmcli", "-t", "-f", "DHCP4.OPTION", "device", "show", interface_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    options = _parse_nmcli_options(completed.stdout)
    if "expiry" in options:
        try:
            return int(options["expiry"])
        except ValueError:
            return None

    if "dhcp_lease_time" in options:
        try:
            lease_seconds = int(options["dhcp_lease_time"])
        except ValueError:
            return None
        return int(time.time()) + lease_seconds

    return None


def _detect_windows_lease_expiration_epoch(ip_address: str) -> int | None:
    script = (
        "$nics = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object {$_.IPEnabled -and $_.DHCPEnabled};"
        "$rows = foreach ($nic in $nics) {"
        "if (-not $nic.DHCPLeaseExpires) { continue };"
        "foreach ($ip in $nic.IPAddress) { [PSCustomObject]@{ip=$ip; lease=$nic.DHCPLeaseExpires} }"
        "};"
        "$rows | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    payload = (completed.stdout or "").strip()
    if not payload:
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("ip") != ip_address:
            continue
        lease = row.get("lease")
        if not isinstance(lease, str):
            continue
        parsed = _parse_windows_dmtf_to_epoch(lease)
        if parsed is not None:
            return parsed

    return None


def _parse_windows_dmtf_to_epoch(lease: str) -> int | None:
    value = lease[6:-2]
    return int(value)/1000 - datetime.now().second 

def resolve_expiration_epoch(interface_name: str, ip_address: str) -> int | None:
    if sys.platform.startswith("win"):
        return _detect_windows_lease_expiration_epoch(ip_address)
    return _detect_linux_lease_expiration_epoch(interface_name)


class ClientService:
    def __init__(self, config: AppConfig) -> None:
        cfg = config.data
        self.room = str(cfg["room"])
        self.network_name = str(cfg["network_name"])
        self.client_port = int(cfg.get("client_port", 8765))
        self.state_store = JsonStore(cfg.get("state_path", "data/client_state.json"))
        self.hostname = socket.gethostname()
        
        self.app = FastAPI(title="VODIN Client")
        self.app.get("/info")(self.info)

    def _interface(self):
        return find_interface_by_name(self.network_name)

    def payload(self, host) -> dict[str, Any]:
        iface = find_interface_by_ip(host) #self._interface()
        return {
            "room": self.room,
            "hostname": self.hostname,
            "mac": iface.mac,
            "exp": resolve_expiration_epoch(iface.name, iface.ip),
            "ip": iface.ip,
            "client_port": self.client_port
        }

    async def info(self, request: Request):
        return self.payload(request.client.host)

def create_client_service(config_path: str | Path) -> ClientService:
    config = AppConfig.load(config_path)
    return ClientService(config)
