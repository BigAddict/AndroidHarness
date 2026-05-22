"""Atomic load + write for ~/.androidharness/config.yaml.

The Settings UI reads via load() on every request (the file is small) and
writes via write(cfg) which serializes to a sibling .tmp file then atomically
replaces the real file. On any failure the original file is left intact.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from androidharness.config import (
    CONFIG_HEADER,
    AndroidHarnessConfig,
    ConfigError,
    load_config,
)


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> AndroidHarnessConfig:
        return load_config(self.path)

    def write(self, cfg: AndroidHarnessConfig) -> AndroidHarnessConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump(
            cfg.model_dump(mode="json"),
            sort_keys=False,
            default_flow_style=False,
        )
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(CONFIG_HEADER + body)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return cfg


__all__ = ["ConfigStore", "ConfigError"]
