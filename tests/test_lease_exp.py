import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from vodin.client import _parse_nmcli_options


def test_parse_nmcli_options():
    raw = "DHCP4.OPTION[1]:expiry=1717000000\nDHCP4.OPTION[2]:dhcp_lease_time=3600\n"
    parsed = _parse_nmcli_options(raw)
    assert parsed["expiry"] == "1717000000"
    assert parsed["dhcp_lease_time"] == "3600"
