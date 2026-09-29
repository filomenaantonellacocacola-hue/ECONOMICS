"""Almacenamiento en Parquet particionado por periodo.

Cada dataset vive en ``<root>/<periodo>/data.parquet`` (p.ej. ``2026-09`` o ``2026``).
Solo se reescriben las particiones cuyo contenido cambio, para que el historial de
git crezca poco con cada actualizacion diaria.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

FILE_NAME = "data.parquet"


def _period_labels(dates: pd.Series, freq: str) -> pd.Series:
    dates = pd.to_datetime(dates)
    if freq == "M":
        return dates.dt.strftime("%Y-%m")
    if freq == "Y":
        return dates.dt.strftime("%Y")
    raise ValueError(f"freq no soportada: {freq}")


def _normalize(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return df.sort_values(keys).reset_index(drop=True)


def write_partitioned(
    df: pd.DataFrame,
    root: Path,
    keys: list[str],
    date_col: str = "date",
    freq: str = "M",
) -> list[Path]:
    """Hace upsert de ``df`` en las particiones de ``root``.

    Las filas nuevas reemplazan a las existentes con las mismas ``keys``.
    Devuelve la lista de archivos que se escribieron.
    """
    if df.empty:
        return []
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    written = []
    for label, chunk in df.groupby(_period_labels(df[date_col], freq), sort=True):
        path = Path(root) / label / FILE_NAME
        if path.exists():
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, chunk], ignore_index=True)
            merged = merged.drop_duplicates(subset=keys, keep="last")
            merged = _normalize(merged, keys)
            if _same(existing, merged, keys):
                continue
        else:
            merged = _normalize(chunk.drop_duplicates(subset=keys, keep="last"), keys)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path, index=False)
        written.append(path)
    return written


def _same(existing: pd.DataFrame, merged: pd.DataFrame, keys: list[str]) -> bool:
    if len(existing) != len(merged) or list(existing.columns) != list(merged.columns):
        return False
    a = _normalize(existing, keys)
    try:
        pd.testing.assert_frame_equal(a, merged, check_dtype=False, check_exact=False)
    except AssertionError:
        return False
    return True


def read_dataset(root: Path) -> pd.DataFrame:
    files = sorted(Path(root).glob(f"*/{FILE_NAME}"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
