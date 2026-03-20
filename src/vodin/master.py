from __future__ import annotations

import asyncio
import logging
import subprocess
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from .config import AppConfig
from .network import find_interface_by_ip, InterfaceInfo
from .storage import JsonStore

logger = logging.getLogger(__name__)


class ClientUpdateBody(BaseModel):
    payload: dict[str, Any]
    signature: str


class MasterService:
    def __init__(self, config: AppConfig) -> None:
        cfg = config.data
        self.client_port = int(cfg.get("client_port", 8765))
        self.scan_timeout = float(cfg.get("scan_timeout", 0.8))
        self.clients_store = JsonStore(cfg.get("clients_store_path", "data/clients.json"))
        self.hosts_update = str(cfg.get("hosts_update_command", 'echo "{host}    {name}" | tee -a /etc/hosts'))
        self.master_port = int(cfg.get("master_port", 9876))

        self.app = FastAPI(title="VODIN Master")
        self.app.get("/scan")(self.trigger_scan)


    async def trigger_scan(self, request: Request):
        logger.info("Scan started")
        found = await self.scan_network(request.client.host)
        return {"found": len(found), "clients": found}

    async def scan_network(self, ip) -> list[dict[str, Any]]:
        iface: InterfaceInfo = find_interface_by_ip(ip)
        network: IPv4Network = iface.network
        print(iface.netmask)
        candidates = [str(ip) for ip in network.hosts()]
        #print(candidates)

        found: list[dict[str, Any]] = []

        limits = httpx.Limits(max_keepalive_connections=32, max_connections=32)
        async with httpx.AsyncClient(timeout=self.scan_timeout, limits=limits) as client:
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
            self.refresh_hosts(current)

        return found

    async def _probe_host(self, http_client: httpx.AsyncClient, ip: str) -> dict[str, Any] | None:
        base = f"http://{ip}:{self.client_port}"
        try:
            response = await http_client.get(f"{base}/info")
            response.raise_for_status()
            logger.debug(ip, response)
            return response.json()
        except Exception as e:
            logger.debug(f"{ip} {type(e)}")
            return None

    def refresh_hosts(self, clients: dict[str, Any]) -> None:
        if not self.hosts_update:
            return
        subprocess.run("""echo "127.0.0.1               localhost.localdomain localhost
::1             localhost6.localdomain6 localhost6" | sudo tee /etc/hosts
        """, shell=True, check=False)
        """TODO: 
        read hosts, 
        remove all lines with same hostnames as was found,
        remove all lines with same ip as was found
        add new lines with found"""
        for hostname in sorted(clients.keys()):
            item = clients[hostname]
            cmd = self.hosts_update.format(host=str(item.get("ip", "")), name=str(item.get("hostname", hostname)))
            subprocess.run(cmd, shell=True, check=False)


def create_master_service(config_path: str | Path) -> MasterService:
    config = AppConfig.load(config_path)
    return MasterService(config)
