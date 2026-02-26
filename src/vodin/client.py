from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import time
from datetime import datetime, timezone
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


def detect_lease_expiration_epoch(interface_name: str) -> int | None:
    """Best-effort DHCP lease expiration timestamp (UTC epoch).

    Returns None when OS/tooling does not expose lease expiration.
    """
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
            "veyon-version": self.veyon_version,
            "exp": detect_lease_expiration_epoch(iface.name),
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
        previous_ip = None
        while True:
            try:
                current_payload = self.payload()
                current_ip = current_payload["ip"]
                if previous_ip and previous_ip != current_ip:
                    await self.notify_master(current_payload)
                previous_ip = current_ip
            except Exception as exc:  # noqa: BLE001
                logger.warning("ip watchdog loop failed: %s", exc)
            await asyncio.sleep(self.watchdog_interval_seconds)

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
