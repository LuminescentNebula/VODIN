import asyncio
import pytest
from unittest.mock import AsyncMock

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("pydantic")


class DummyStore:
    def __init__(self, initial=None):
        self.data = initial or {}

    def read(self):
        return dict(self.data)

    def write(self, state):
        self.data = dict(state)


def test_ip_watchdog_uses_fast_interval_on_low_lease(monkeypatch):
    from vodin.client import ClientService

    service = ClientService.__new__(ClientService)
    service.watchdog_interval_seconds = 20
    service.watchdog_fast_interval_seconds = 3
    service.watchdog_lease_warning_seconds = 10
    service.state_store = DummyStore({"last_ip": "10.0.0.1"})
    service.notify_master = AsyncMock()
    service.payload = lambda: {"ip": "10.0.0.2", "exp": 105}

    monkeypatch.setattr("vodin.client.time.time", lambda: 100)

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise RuntimeError("stop")

    monkeypatch.setattr("vodin.client.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(service.ip_watchdog())

    assert sleeps == [3]
    service.notify_master.assert_awaited_once()
    assert service.state_store.data["last_ip"] == "10.0.0.2"
    assert service.state_store.data["last_payload"]["ip"] == "10.0.0.2"


def test_ip_watchdog_fallback_without_lease_data(monkeypatch, caplog):
    from vodin.client import ClientService

    service = ClientService.__new__(ClientService)
    service.watchdog_interval_seconds = 12
    service.watchdog_fast_interval_seconds = 2
    service.watchdog_lease_warning_seconds = 10
    service.state_store = DummyStore()
    service.notify_master = AsyncMock()
    service.payload = lambda: {"ip": "10.0.0.3", "iat": None}

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise RuntimeError("stop")

    monkeypatch.setattr("vodin.client.asyncio.sleep", fake_sleep)

    with caplog.at_level("INFO"):
        with pytest.raises(RuntimeError, match="stop"):
            asyncio.run(service.ip_watchdog())

    assert sleeps == [12]
    service.notify_master.assert_not_called()
    assert "lease data unavailable" in caplog.text
