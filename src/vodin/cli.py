from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from .client import DEFAULT_CLIENT_PORT, create_client_service
from .master import create_master_service


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vodin")
    parser.add_argument("mode", choices=["client", "master"])
    parser.add_argument("--config", required=True, help="Path to role-specific YAML config file")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    if args.mode == "client":
        service = create_client_service(args.config)
        port = args.port or DEFAULT_CLIENT_PORT
        config = uvicorn.Config(service.app, host=args.host, port=port, log_level=args.log_level.lower())
        server = uvicorn.Server(config)
        loop = asyncio.get_event_loop()
        loop.create_task(service.ip_watchdog())
        loop.run_until_complete(server.serve())
        return

    service = create_master_service(args.config)
    port = args.port or 9876
    uvicorn.run(service.app, host=args.host, port=port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
