from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AppConfig:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        cfg_path = Path(path)
        with cfg_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return cls(data=raw)

    def section(self, key: str) -> dict[str, Any]:
        value = self.data.get(key, {})
        if not isinstance(value, dict):
            raise ValueError(f"Config section '{key}' must be an object")
        return value
