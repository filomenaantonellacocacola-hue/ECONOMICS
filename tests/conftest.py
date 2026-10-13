"""Ninguna prueba toca data/ del repo: todas las rutas de datos apuntan a una carpeta temporal."""
from pathlib import Path

import pytest

from econ import config


@pytest.fixture(autouse=True)
def _isolated_data_dirs(tmp_path, monkeypatch):
    real = Path(config.DATA_DIR)
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    for attr in dir(config):
        value = getattr(config, attr)
        if attr.endswith("_DIR") and isinstance(value, Path) and value.parent == real:
            monkeypatch.setattr(config, attr, data / value.name)
