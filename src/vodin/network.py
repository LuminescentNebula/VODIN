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

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(f"{self.ip}/{self.netmask}", strict=False)


def _iter_ipv4_interfaces() -> Iterable[InterfaceInfo]:
    interfaces = psutil.net_if_addrs()
    for name, addresses in interfaces.items():
        for address in addresses:
            if address.family == socket.AF_INET and address.address and address.netmask:
                yield InterfaceInfo(name=name, ip=address.address, netmask=address.netmask)


def find_interface_for_network(cidr: str) -> InterfaceInfo:
    target_network = ipaddress.ip_network(cidr, strict=False)
    for iface in _iter_ipv4_interfaces():
        if ipaddress.ip_address(iface.ip) in target_network:
            return iface
    raise RuntimeError(f"No active IPv4 interface found in network '{cidr}'")


def resolve_network_by_name(network_name: str, named_networks: dict[str, str]) -> str:
    network_cidr = named_networks.get(network_name)
    if not network_cidr:
        available = ", ".join(sorted(named_networks)) or "<empty>"
        raise RuntimeError(
            f"Unknown network '{network_name}'. Configure it in named_networks. Available: {available}"
        )
    return network_cidr
