from __future__ import annotations

import asyncio
import csv
import json
import logging
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import AppConfig
from .crypto import load_private_key, sign_message, verify_signature
from .network import find_interface_for_network, resolve_network_by_name
from .storage import JsonStore

logger = logging.getLogger(__name__)


class ClientUpdateBody(BaseModel):
    payload: dict[str, Any]
    signature: str


class MasterService:
    def __init__(self, config: AppConfig) -> None:
        cfg = config.data
        self.network_name = str(cfg["network_name"])
        named_networks = cfg.get("named_networks", {})
        self.network_cidr = resolve_network_by_name(self.network_name, named_networks)
        self.client_port = int(cfg.get("client_port", 8765))
        self.scan_timeout = float(cfg.get("scan_timeout", 0.8))
        self.private_key = load_private_key(cfg["master_private_key_path"])
        self.clients_store = JsonStore(cfg.get("clients_store_path", "data/clients.json"))
        self.veyon_cmd = str(
            cfg.get(
                "veyon_update_command",
                "veyon-cli networkobjects import {clients_file} format \"%location%;%name%;%host%;%mac%\"",
            )
        )
        self.veyon_cleanup_cmd = str(cfg.get("veyon_cleanup_command", "veyon-cli remove {name}"))
        self.veyon_start_cmd = str(cfg.get("veyon_start_command", "veyon-master"))
        self.master_port = int(cfg.get("master_port", 9876))

        self.app = FastAPI(title="VODIN Master")
        self.app.post("/client/update")(self.client_update)
        self.app.post("/scan")(self.trigger_scan)
        self.app.get("/scan")(self.trigger_scan)


    async def trigger_scan(self):
        found = await self.scan_network()
        return {"found": len(found), "clients": found}

    async def client_update(self, body: ClientUpdateBody):
        payload = body.payload
        hostname = payload.get("hostname")
        if not hostname:
            raise HTTPException(status_code=400, detail="hostname is required")

        clients = self.clients_store.read()
        existing = clients.get(hostname)
        if not existing:
            raise HTTPException(status_code=404, detail="Client is not registered")

        client_pub_pem = existing.get("client_public_key", "").encode("utf-8")
        client_pub_key = serialization.load_pem_public_key(client_pub_pem)
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if not verify_signature(client_pub_key, serialized_payload, body.signature):
            raise HTTPException(status_code=403, detail="Invalid client signature")

        old_ip = existing.get("ip")
        clients[hostname] = payload
        clients[hostname]["updated_at"] = int(datetime.now(tz=timezone.utc).timestamp())
        self.clients_store.write(clients)

        if old_ip != payload.get("ip"):
            logger.info("Client %s changed ip %s -> %s", hostname, old_ip, payload.get("ip"))
            was_running = self.is_veyon_running()
            if was_running:
                self.notify_operator(
                    f"Veyon is running and will be restarted after configuration refresh for {hostname}."
                )
                self.stop_veyon()
            self.refresh_veyon(clients)
            if was_running:
                self.start_veyon()

        return {"status": "ok"}

    async def scan_network(self) -> list[dict[str, Any]]:
        iface = find_interface_for_network(self.network_cidr)
        network: IPv4Network = iface.network
        candidates = [str(ip) for ip in network.hosts()]
        found: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=self.scan_timeout) as client:
            tasks = [self._probe_host(client, ip) for ip in candidates]
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    found.append(result)

        if found:
            current = self.clients_store.read()
            for item in found:
                current[item["hostname"]] = item
            self.clients_store.write(current)
            self.refresh_veyon(current)

        return found

    async def _probe_host(self, http_client: httpx.AsyncClient, ip: str) -> dict[str, Any] | None:
        base = f"http://{ip}:{self.client_port}"
        try:
            response = await http_client.get(f"{base}/info")
            response.raise_for_status()
            payload = response.json()
            await self._announce_master(http_client, base)
            return payload
        except Exception:
            return None

    async def _announce_master(self, http_client: httpx.AsyncClient, client_base: str) -> None:
        timestamp = int(datetime.now(tz=timezone.utc).timestamp())
        master_ip = find_interface_for_network(self.network_cidr).ip
        master_url = f"http://{master_ip}:{self.master_port}"
        message = f"{master_url}|{timestamp}".encode("utf-8")
        signature = sign_message(self.private_key, message)
        data = {"master_url": master_url, "timestamp": timestamp, "signature": signature}
        response = await http_client.post(f"{client_base}/master/announce", json=data)
        response.raise_for_status()

    def refresh_veyon(self, clients: dict[str, Any]) -> None:
        if not self.veyon_cmd:
            return

        rows = self._build_veyon_import_rows(clients)
        payload = json.dumps({"clients": rows}, ensure_ascii=False)
        clients_file = self._write_veyon_import_file(rows)
        try:
            if self.veyon_cleanup_cmd:
                for hostname in sorted(clients.keys()):
                    item = clients[hostname]
                    cleanup_cmd = self.veyon_cleanup_cmd.format(name=item.get("room", ""))
                    subprocess.run(cleanup_cmd, shell=True, check=False)
            cmd = self.veyon_cmd.format(clients_file=clients_file, clients_json=payload)
            subprocess.run(cmd, shell=True, check=False)
        finally:
            Path(clients_file).unlink(missing_ok=True)

    def _build_veyon_import_rows(self, clients: dict[str, Any]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for hostname in sorted(clients.keys()):
            item = clients[hostname]
            rows.append(
                {
                    "location": str(item.get("room", "")),
                    "name": str(item.get("hostname", hostname)),
                    "host": str(item.get("ip", "")),
                    "mac": str(item.get("mac", "")),
                }
            )
        return rows

    def _write_veyon_import_file(self, rows: list[dict[str, str]]) -> str:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as handle:
            writer = csv.writer(handle, delimiter=";")
            for row in rows:
                writer.writerow([row["location"], row["name"], row["host"], row["mac"]])
            return handle.name

    def is_veyon_running(self) -> bool:
        system = platform.system()
        if system == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq veyon-master.exe"],
                check=False,
                capture_output=True,
                text=True,
            )
            return "veyon-master.exe" in result.stdout.lower()

        result = subprocess.run(
            ["pgrep", "-f", "veyon-master"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def stop_veyon(self) -> None:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["taskkill", "/IM", "veyon-master.exe", "/F"], check=False)
            return

        subprocess.run(["pkill", "-f", "veyon-master"], check=False)

    def start_veyon(self) -> None:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["cmd", "/c", "start", "", self.veyon_start_cmd], check=False)
            return

        subprocess.Popen([self.veyon_start_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def notify_operator(self, message: str) -> None:
        logger.warning(message)
        system = platform.system()
        try:
            if system == "Linux" and shutil.which("notify-send"):
                subprocess.run(["notify-send", "VODIN", message], check=False)
            elif system == "Darwin" and shutil.which("osascript"):
                subprocess.run(
                    ["osascript", "-e", f'display notification "{message}" with title "VODIN"'],
                    check=False,
                )
            elif system == "Windows":
                script = (
                    "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                    f"[System.Windows.Forms.MessageBox]::Show('{message}','VODIN')"
                )
                subprocess.run(["powershell", "-Command", script], check=False)
        except Exception:
            logger.debug("Operator notification failed", exc_info=True)


def create_master_service(config_path: str | Path) -> MasterService:
    config = AppConfig.load(config_path)
    return MasterService(config)
