from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable

import psutil


@dataclass(slots=True)
class InterfaceInfo:
    name: str
    ip: str
    netmask: str
    mac: str | None = None

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(f"{self.ip}/{self.netmask}", strict=False)


def _iter_ipv4_interfaces() -> Iterable[InterfaceInfo]:
    interfaces = psutil.net_if_addrs()
    for name, addresses in interfaces.items():
        mac_address = _extract_mac_address(addresses)
        for address in addresses:
            if address.family == socket.AF_INET and address.address and address.netmask:
                yield InterfaceInfo(name=name, ip=address.address, netmask=address.netmask, mac=mac_address)


def _extract_mac_address(addresses: list[object]) -> str | None:
    for address in addresses:
        family = getattr(address, "family", None)
        value = getattr(address, "address", "")
        if family not in {getattr(psutil, "AF_LINK", None), getattr(socket, "AF_PACKET", None)}:
            continue
        normalized = _normalize_mac(value)
        if normalized:
            return normalized
    return None


def _normalize_mac(value: str) -> str | None:
    compact = value.replace(":", "").replace("-", "").strip().lower()
    if len(compact) != 12:
        return None
    if any(char not in "0123456789abcdef" for char in compact):
        return None
    if compact == "000000000000":
        return None
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))

def find_interface_by_ip(ip:str) -> InterfaceInfo:
    target_network = ipaddress.ip_network(ip, strict=False)
    for iface in _iter_ipv4_interfaces():
        if ipaddress.ip_address(iface.ip) in target_network:
            return iface
    raise RuntimeError(f"No interface for {ip}")


def find_interface_by_name(network_name: str) -> InterfaceInfo:
    for iface in _iter_ipv4_interfaces():
        if iface.name == network_name:
            return iface
    raise RuntimeError(f"No active IPv4 interface found in network '{network_name}'")


