import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")
pytest.importorskip("cryptography")

from types import SimpleNamespace

from vodin import master
from vodin.master import ClientUpdateBody, MasterService


class DummyStore:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def write(self, data):
        self.data = data


def make_service_with_store(store_data):
    svc = object.__new__(MasterService)
    svc.clients_store = DummyStore(store_data)
    return svc


def test_client_update_restarts_veyon_when_running(monkeypatch):
    payload = {"hostname": "pc1", "ip": "10.0.0.2"}
    existing = {"pc1": {"hostname": "pc1", "ip": "10.0.0.1", "client_public_key": "pem"}}
    svc = make_service_with_store(existing)

    monkeypatch.setattr(master.serialization, "load_pem_public_key", lambda *_: object())
    monkeypatch.setattr(master, "verify_signature", lambda *_: True)

    calls = []
    monkeypatch.setattr(svc, "is_veyon_running", lambda: True)
    monkeypatch.setattr(svc, "notify_operator", lambda msg: calls.append(("notify", msg)))
    monkeypatch.setattr(svc, "stop_veyon", lambda: calls.append(("stop", None)))
    monkeypatch.setattr(svc, "refresh_veyon", lambda clients: calls.append(("refresh", clients["pc1"]["ip"])))
    monkeypatch.setattr(svc, "start_veyon", lambda: calls.append(("start", None)))

    import asyncio
    result = asyncio.run(svc.client_update(ClientUpdateBody(payload=payload, signature="sig")))

    assert result == {"status": "ok"}
    assert [step for step, _ in calls] == ["notify", "stop", "refresh", "start"]


def test_client_update_refreshes_only_when_veyon_stopped(monkeypatch):
    payload = {"hostname": "pc1", "ip": "10.0.0.2"}
    existing = {"pc1": {"hostname": "pc1", "ip": "10.0.0.1", "client_public_key": "pem"}}
    svc = make_service_with_store(existing)

    monkeypatch.setattr(master.serialization, "load_pem_public_key", lambda *_: object())
    monkeypatch.setattr(master, "verify_signature", lambda *_: True)

    calls = []
    monkeypatch.setattr(svc, "is_veyon_running", lambda: False)
    monkeypatch.setattr(svc, "notify_operator", lambda msg: calls.append(("notify", msg)))
    monkeypatch.setattr(svc, "stop_veyon", lambda: calls.append(("stop", None)))
    monkeypatch.setattr(svc, "refresh_veyon", lambda clients: calls.append(("refresh", clients["pc1"]["ip"])))
    monkeypatch.setattr(svc, "start_veyon", lambda: calls.append(("start", None)))

    import asyncio
    asyncio.run(svc.client_update(ClientUpdateBody(payload=payload, signature="sig")))

    assert calls == [("refresh", "10.0.0.2")]


def test_is_veyon_running_linux(monkeypatch):
    svc = object.__new__(MasterService)

    monkeypatch.setattr(master.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        master.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="123"),
    )

    assert svc.is_veyon_running() is True


def test_is_veyon_running_windows(monkeypatch):
    svc = object.__new__(MasterService)

    monkeypatch.setattr(master.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        master.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="veyon-master.exe"),
    )

    assert svc.is_veyon_running() is True


def test_stop_veyon_linux(monkeypatch):
    svc = object.__new__(MasterService)

    calls = []
    monkeypatch.setattr(master.platform, "system", lambda: "Linux")
    monkeypatch.setattr(master.subprocess, "run", lambda cmd, check=False: calls.append(cmd))

    svc.stop_veyon()

    assert calls == [["pkill", "-f", "veyon-master"]]


def test_start_veyon_linux(monkeypatch):
    svc = object.__new__(MasterService)
    svc.veyon_start_cmd = "veyon-master"

    calls = []
    monkeypatch.setattr(master.platform, "system", lambda: "Linux")
    monkeypatch.setattr(master.subprocess, "Popen", lambda cmd, **kwargs: calls.append(cmd))

    svc.start_veyon()

    assert calls == [["veyon-master"]]


def test_notify_operator_linux(monkeypatch):
    svc = object.__new__(MasterService)

    calls = []
    monkeypatch.setattr(master.platform, "system", lambda: "Linux")
    monkeypatch.setattr(master.shutil, "which", lambda _: "/usr/bin/notify-send")
    monkeypatch.setattr(master.subprocess, "run", lambda cmd, check=False: calls.append(cmd))

    svc.notify_operator("hello")

    assert calls == [["notify-send", "VODIN", "hello"]]


def test_refresh_veyon_uses_clients_file_and_cleanup(monkeypatch):
    svc = object.__new__(MasterService)
    svc.veyon_cleanup_cmd = "cleanup {clients_file}"
    svc.veyon_cmd = "import {clients_file}"

    calls = []

    def fake_run(cmd, shell=True, check=False):
        file_path = cmd.split(" ", 1)[1]
        content = open(file_path, encoding="utf-8").read().strip().splitlines()
        calls.append((cmd, content))

    monkeypatch.setattr(master.subprocess, "run", fake_run)

    svc.refresh_veyon(
        {
            "pc2": {"hostname": "pc2", "ip": "10.0.0.2", "room": "202"},
            "pc1": {"hostname": "pc1", "ip": "10.0.0.1", "room": "101"},
        }
    )

    assert len(calls) == 2
    assert calls[0][0].startswith("cleanup ")
    assert calls[1][0].startswith("import ")
    assert calls[0][1] == calls[1][1]
    assert calls[1][1] == ["101;pc1;10.0.0.1;", "202;pc2;10.0.0.2;"]


def test_build_veyon_import_rows_includes_mac():
    svc = object.__new__(MasterService)

    rows = svc._build_veyon_import_rows({"pc1": {"hostname": "pc1", "ip": "10.0.0.1", "room": "101", "mac": "aa:bb:cc:dd:ee:ff"}})

    assert rows == [
        {"location": "101", "name": "pc1", "host": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff"}
    ]
