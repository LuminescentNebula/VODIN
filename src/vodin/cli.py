from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from .autostart import (
    get_client_autostart_status,
    install_client_autostart,
    uninstall_client_autostart,
)
from .client import create_client_service
from .master import create_master_service
from .network import find_interface_by_name


DEFAULT_MASTER_PORT = 9876


def run_client(config_path: str, host: str | None, port: int | None, log_level: str) -> None:
    service = create_client_service(config_path)
    bind_host = host
    if bind_host is None:
        bind_host = find_interface_by_name(service.network_name).ip

    uvicorn.run(
        service.app,
        host=bind_host,
        port=port or service.client_port,
        log_level=log_level.lower(),
    )

def run_master(config_path: str, host: str, port: int, log_level: str) -> None:
    service = create_master_service(config_path)
    uvicorn.run(service.app, host=host, port=port, log_level=log_level.lower())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vodin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    client = subparsers.add_parser("client")
    client.add_argument("--config", required=True, help="Path to client YAML config file")
    client.add_argument("--name", default="Study.MOS")
    client.add_argument("--host", default="0.0.0.0")
    client.add_argument("--port", type=int)
    client.add_argument("--log-level", default="INFO")

    master = subparsers.add_parser("master")
    master.add_argument("--config", required=True, help="Path to master YAML config file")
    master.add_argument("--host", default="0.0.0.0")
    master.add_argument("--port", type=int)
    master.add_argument("--log-level", default="INFO")

    install_autostart = subparsers.add_parser("client-install-autostart")
    install_autostart.add_argument("--config", required=True, help="Path to client YAML config file")
    install_autostart.add_argument(
        "--name",
        help="Custom unit name on Linux (.service) or task name on Windows",
    )

    status_autostart = subparsers.add_parser("client-autostart-status")
    status_autostart.add_argument(
        "--name",
        help="Custom unit name on Linux (.service) or task name on Windows",
    )

    uninstall_autostart = subparsers.add_parser("client-uninstall-autostart")
    uninstall_autostart.add_argument(
        "--name",
        help="Custom unit name on Linux (.service) or task name on Windows",
    )

    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.command == "client":
        log_level = args.log_level.upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
        run_client(args.config, args.host, args.port, log_level)
        return

    if args.command == "master":
        log_level = args.log_level.upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
        run_master(args.config, args.host, args.port or DEFAULT_MASTER_PORT, log_level)
        return

    if args.command == "client-install-autostart":
        print(install_client_autostart(args.config, args.name))
        return

    if args.command == "client-autostart-status":
        print(get_client_autostart_status(args.name))
        return

    if args.command == "client-uninstall-autostart":
        print(uninstall_client_autostart(args.name))


if __name__ == "__main__":
    main()
