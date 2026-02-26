import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

import vodin.client as client
from vodin.client import _parse_nmcli_options, _parse_windows_dmtf_to_epoch, resolve_expiration_epoch


def test_parse_nmcli_options():
    raw = "DHCP4.OPTION[1]:expiry=1717000000\nDHCP4.OPTION[2]:dhcp_lease_time=3600\n"
    parsed = _parse_nmcli_options(raw)
    assert parsed["expiry"] == "1717000000"
    assert parsed["dhcp_lease_time"] == "3600"


def test_resolve_expiration_epoch_returns_none_when_not_detected(monkeypatch):
    monkeypatch.setattr(client, "detect_lease_expiration_epoch", lambda *_: None)
    assert resolve_expiration_epoch("eth0", "192.168.1.10") is None


def test_detect_windows_lease_expiration_epoch_by_ip(monkeypatch):
    sample = '[{"ip":"192.168.1.10","lease":"20250101000000.000000+000"}]'

    class Dummy:
        returncode = 0
        stdout = sample

    monkeypatch.setattr(client.subprocess, "run", lambda *args, **kwargs: Dummy())
    assert client._detect_windows_lease_expiration_epoch("192.168.1.10") == 1735689600


def test_parse_windows_dmtf_invalid_returns_none():
    assert _parse_windows_dmtf_to_epoch("invalid") is None
    assert _parse_windows_dmtf_to_epoch("999") is None
