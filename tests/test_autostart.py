from __future__ import annotations

from pathlib import Path

import pytest

from vodin import autostart


def test_detect_client_command_prefers_vodin_client(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/vodin-client" if name == "vodin-client" else None)

    executable, args = autostart._detect_client_command("./client.yml")

    assert executable == "/usr/bin/vodin-client"
    assert args[0] == "--config"
    assert Path(args[1]).is_absolute()


def test_install_linux_writes_unit_and_enables(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(autostart, "_detect_client_command", lambda config: ("/usr/bin/vodin", ["client", "--config", "/tmp/client.yml"]))
    monkeypatch.setattr(autostart, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(autostart, "Path", lambda value: tmp_path / value.strip("/"))

    message = autostart._install_linux("client.yml", "vodin-client.service")

    unit_file = tmp_path / "etc/systemd/system/vodin-client.service"
    assert "Installed systemd unit" in message
    assert unit_file.exists()
    content = unit_file.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/vodin client --config /tmp/client.yml" in content
    assert ["systemctl", "daemon-reload"] in calls
    assert ["systemctl", "enable", "--now", "vodin-client.service"] in calls


def test_install_dispatches_by_platform(monkeypatch):
    monkeypatch.setattr(autostart.platform, "system", lambda: "Windows")
    monkeypatch.setattr(autostart, "_install_windows", lambda config, name: f"win:{name}:{config}")

    assert autostart.install_client_autostart("client.yml", "Task") == "win:Task:client.yml"


@pytest.mark.parametrize("platform_name", ["Darwin", "FreeBSD"])
def test_unsupported_platform(platform_name, monkeypatch):
    monkeypatch.setattr(autostart.platform, "system", lambda: platform_name)

    with pytest.raises(autostart.AutostartError):
        autostart.install_client_autostart("client.yml")
