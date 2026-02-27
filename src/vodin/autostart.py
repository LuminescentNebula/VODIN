from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_SYSTEMD_UNIT = "vodin-client.service"
DEFAULT_WINDOWS_TASK = "VODIN Client"


class AutostartError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def _detect_client_command(config_path: str) -> tuple[str, list[str]]:
    config = str(Path(config_path).expanduser().resolve())

    if getattr(sys, "frozen", False):
        return sys.executable, ["client", "--config", config]

    vodin_client = shutil.which("vodin")
    if vodin_client:
        return vodin_client, ["client", "--config", config]

    vodin = shutil.which("vodin")
    if vodin:
        return vodin, ["client", "--config", config]

    return sys.executable, ["-m", "vodin.cli", "client", "--config", config]


def _install_linux(config_path: str, unit_name: str) -> str:
    executable, args = _detect_client_command(config_path)
    exec_start = " ".join(shlex.quote(part) for part in [executable, *args])
    unit_path = Path("/etc/systemd/system") / unit_name

    unit_content = f"""[Unit]
Description=VODIN Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit_content, encoding="utf-8")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "--now", unit_name])
    return f"Installed systemd unit at {unit_path}"


def _status_linux(unit_name: str) -> str:
    result = _run(["systemctl", "status", unit_name, "--no-pager"])
    return result.stdout.strip() or result.stderr.strip()


def _uninstall_linux(unit_name: str) -> str:
    unit_path = Path("/etc/systemd/system") / unit_name
    subprocess.run(["systemctl", "disable", "--now", unit_name], check=False, text=True, capture_output=True)
    if unit_path.exists():
        unit_path.unlink()
    _run(["systemctl", "daemon-reload"])
    return f"Removed systemd unit {unit_name}"


def _build_windows_task_command(config_path: str) -> str:
    executable, args = _detect_client_command(config_path)
    quoted = [f'"{executable}"', *[f'"{arg}"' for arg in args]]
    return " ".join(quoted)


def _install_windows(config_path: str, task_name: str) -> str:
    task_cmd = _build_windows_task_command(config_path)
    _run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "ONSTART",
            "/RL",
            "HIGHEST",
            "/RU",
            "SYSTEM",
            "/TR",
            task_cmd,
            "/F",
        ]
    )
    return f"Installed Scheduled Task '{task_name}'"


def _status_windows(task_name: str) -> str:
    result = _run(["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"])
    return result.stdout.strip() or result.stderr.strip()


def _uninstall_windows(task_name: str) -> str:
    _run(["schtasks", "/Delete", "/TN", task_name, "/F"])
    return f"Removed Scheduled Task '{task_name}'"


def install_client_autostart(config_path: str, name: str | None = None) -> str:
    system = platform.system()

    if system == "Linux":
        return _install_linux(config_path, name or DEFAULT_SYSTEMD_UNIT)
    if system == "Windows":
        return _install_windows(config_path, name or DEFAULT_WINDOWS_TASK)

    raise AutostartError(f"Autostart is not supported on this platform: {system}")


def get_client_autostart_status(name: str | None = None) -> str:
    system = platform.system()

    if system == "Linux":
        return _status_linux(name or DEFAULT_SYSTEMD_UNIT)
    if system == "Windows":
        return _status_windows(name or DEFAULT_WINDOWS_TASK)

    raise AutostartError(f"Autostart is not supported on this platform: {system}")


def uninstall_client_autostart(name: str | None = None) -> str:
    system = platform.system()

    if system == "Linux":
        return _uninstall_linux(name or DEFAULT_SYSTEMD_UNIT)
    if system == "Windows":
        return _uninstall_windows(name or DEFAULT_WINDOWS_TASK)

    raise AutostartError(f"Autostart is not supported on this platform: {system}")
