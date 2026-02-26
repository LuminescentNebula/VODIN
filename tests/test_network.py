import pytest

pytest.importorskip("psutil")

from vodin.network import resolve_network_by_name


def test_resolve_network_by_name():
    named = {"lan-a": "10.0.0.0/24"}
    assert resolve_network_by_name("lan-a", named) == "10.0.0.0/24"


def test_resolve_network_by_name_missing():
    with pytest.raises(RuntimeError):
        resolve_network_by_name("missing", {"lan-a": "10.0.0.0/24"})
