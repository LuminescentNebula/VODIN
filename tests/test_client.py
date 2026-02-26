import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from vodin.client import detect_veyon_version


def test_detect_veyon_version_returns_string():
    assert isinstance(detect_veyon_version(), str)
