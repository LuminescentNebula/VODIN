from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import AppConfig
from .crypto import export_public_key, load_private_key, load_public_key, sign_message, verify_signature
from .network import find_interface_for_network, resolve_network_by_name
from .storage import JsonStore

logger = logging.getLogger(__name__)


class MasterAnnouncePayload(BaseModel):
    master_url: str
    timestamp: int
    signature: str


def detect_veyon_version() -> str:
    try:
        completed = subprocess.run(
            ["veyon-cli", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        line = (completed.stdout or completed.stderr).strip().splitlines()
        return line[0] if line else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


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


def _parse_windows_dmtf_to_epoch(value: str) -> int | None:
    # Example: 20261231235959.000000+180
    match = re.fullmatch(r"(\d{14})\.\d{6}([+-])(\d{3})", value.strip())
    if not match:
        return None

    base_raw, sign, offset_minutes_raw = match.groups()
    try:
        local_dt = datetime.strptime(base_raw, "%Y%m%d%H%M%S")
        offset_minutes = int(offset_minutes_raw)
    except ValueError:
        return None

    offset = timedelta(minutes=offset_minutes)
    if sign == "-":
        offset = -offset

    utc_dt = (local_dt - offset).replace(tzinfo=timezone.utc)
    return int(utc_dt.timestamp())


def detect_lease_expiration_epoch(interface_name: str, ip_address: str) -> int | None:
    """Best-effort DHCP lease expiration timestamp (UTC epoch)."""
    if sys.platform.startswith("win"):
        return _detect_windows_lease_expiration_epoch(ip_address)
    return _detect_linux_lease_expiration_epoch(interface_name)


def resolve_expiration_epoch(interface_name: str, ip_address: str, fallback_ttl_seconds: int | None) -> int | None:
    detected = detect_lease_expiration_epoch(interface_name, ip_address)
    if detected is not None:
        return detected
    if fallback_ttl_seconds and fallback_ttl_seconds > 0:
        return int(time.time()) + fallback_ttl_seconds
    return None


class ClientService:
    def __init__(self, config: AppConfig) -> None:
        cfg = config.data
        self.room = str(cfg["room"])
        self.network_name = str(cfg["network_name"])
        named_networks = cfg.get("named_networks", {})
        self.network_cidr = resolve_network_by_name(self.network_name, named_networks)
        self.client_port = int(cfg.get("client_port", 8765))
        self.veyon_version = detect_veyon_version()
        self.watchdog_interval_seconds = int(cfg.get("watchdog_interval_seconds", 15))
        self.watchdog_fast_interval_seconds = int(cfg.get("watchdog_fast_interval_seconds", 5))
        self.watchdog_lease_warning_seconds = int(cfg.get("watchdog_lease_warning_seconds", 60))
        fallback_ttl = cfg.get("default_lease_ttl_seconds")
        self.default_lease_ttl_seconds = int(fallback_ttl) if fallback_ttl is not None else None
        self.master_pub_key = load_public_key(cfg["master_public_key_path"])
        self.client_priv_key = load_private_key(cfg["client_private_key_path"])
        self.state_store = JsonStore(cfg.get("state_path", "data/client_state.json"))

        self.app = FastAPI(title="VODIN Client")
        self.app.get("/info")(self.info)
        self.app.post("/master/announce")(self.master_announce)

    def _interface(self):
        return find_interface_for_network(self.network_cidr)

    def payload(self) -> dict[str, Any]:
        iface = self._interface()
        return {
            "room": self.room,
            "hostname": socket.gethostname(),
            "mac": iface.mac,
            "veyon-version": self.veyon_version,
            "exp": resolve_expiration_epoch(iface.name, iface.ip, self.default_lease_ttl_seconds),
            "ip": iface.ip,
            "client_port": self.client_port,
            "client_public_key": export_public_key(self.client_priv_key.public_key()),
            "network": self.network_name,
        }

    async def info(self):
        return self.payload()

    async def master_announce(self, body: MasterAnnouncePayload):
        message = f"{body.master_url}|{body.timestamp}".encode("utf-8")
        if not verify_signature(self.master_pub_key, message, body.signature):
            raise HTTPException(status_code=403, detail="Invalid master signature")

        state = self.state_store.read()
        state["master_url"] = body.master_url
        state["acknowledged_at"] = int(datetime.now(tz=timezone.utc).timestamp())
        self.state_store.write(state)
        return {"status": "ok"}

    async def ip_watchdog(self):
        state = self.state_store.read()
        previous_ip = state.get("last_ip")
        while True:
            sleep_for = self.watchdog_interval_seconds
            try:
                current_payload = self.payload()
                current_ip = current_payload["ip"]
                lease_epoch = current_payload.get("iat")
                if lease_epoch is None:
                    lease_epoch = current_payload.get("exp")

                if lease_epoch is None:
                    logger.info("ip watchdog: lease data unavailable for %s", current_ip)
                else:
                    lease_left = int(lease_epoch) - int(time.time())
                    if lease_left <= self.watchdog_lease_warning_seconds:
                        logger.warning(
                            "ip watchdog: lease left=%ss for ip=%s (threshold=%ss)",
                            lease_left,
                            current_ip,
                            self.watchdog_lease_warning_seconds,
                        )
                        sleep_for = max(1, min(self.watchdog_interval_seconds, self.watchdog_fast_interval_seconds))
                    else:
                        logger.info("ip watchdog: lease left=%ss for ip=%s", lease_left, current_ip)

                if previous_ip and previous_ip != current_ip:
                    state = self.state_store.read()
                    state["last_ip"] = current_ip
                    state["last_payload"] = current_payload
                    state["ip_updated_at"] = int(time.time())
                    self.state_store.write(state)
                    await self.notify_master(current_payload)
                elif not previous_ip:
                    state = self.state_store.read()
                    state["last_ip"] = current_ip
                    self.state_store.write(state)
                previous_ip = current_ip
            except Exception as exc:  # noqa: BLE001
                logger.warning("ip watchdog loop failed: %s", exc)
            await asyncio.sleep(sleep_for)

    async def notify_master(self, payload: dict[str, Any]) -> None:
        state = self.state_store.read()
        master_url = state.get("master_url")
        if not master_url:
            return

        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        signature = sign_message(self.client_priv_key, body)
        data = {"payload": payload, "signature": signature}
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{master_url}/client/update", json=data)
            response.raise_for_status()
        logger.info("Notified master about ip update: %s", payload["ip"])


def create_client_service(config_path: str | Path) -> ClientService:
    config = AppConfig.load(config_path)
    return ClientService(config)
