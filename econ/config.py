"""Rutas y configuracion comun del proyecto."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.environ.get("ECON_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

PRICES_DIR = DATA_DIR / "prices"
MACRO_DIR = DATA_DIR / "macro"
FUNDAMENTALS_DIR = DATA_DIR / "fundamentals"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

UNIVERSE_CSV = CONFIG_DIR / "universe.csv"
MACRO_SERIES_CSV = CONFIG_DIR / "macro_series.csv"

DEFAULT_HISTORY_START = "2015-01-01"
DEFAULT_MACRO_START = "2000-01-01"


def load_universe() -> pd.DataFrame:
    return pd.read_csv(UNIVERSE_CSV, dtype=str, keep_default_na=False)


def load_macro_series() -> pd.DataFrame:
    return pd.read_csv(MACRO_SERIES_CSV, dtype=str, keep_default_na=False)
