"""Series macroeconomicas de la Reserva Federal de St. Louis (FRED).

Con ``FRED_API_KEY`` usa la API oficial (gratis: https://fred.stlouisfed.org/docs/api/api_key.html);
sin llave cae al CSV publico de fredgraph.
"""
from __future__ import annotations

import io
import logging
import os

import pandas as pd
import requests

log = logging.getLogger(__name__)

API_URL = "https://api.stlouisfed.org/fred/series/observations"
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TIMEOUT = 60


def parse_api_json(payload: dict, series_id: str) -> pd.DataFrame:
    obs = payload.get("observations", [])
    df = pd.DataFrame(obs, columns=["date", "value"])
    return _finish(df, series_id)


def parse_csv(text: str, series_id: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    date_col = next(c for c in df.columns if c.lower() in ("date", "observation_date"))
    df = df.rename(columns={date_col: "date", series_id: "value"})[["date", "value"]]
    return _finish(df, series_id)


def _finish(df: pd.DataFrame, series_id: str) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"].replace(".", pd.NA), errors="coerce").astype("float64")
    df = df.dropna(subset=["value"])
    df.insert(0, "series_id", series_id)
    df["source"] = "FRED"
    return df[["source", "series_id", "date", "value"]].reset_index(drop=True)


def fetch_series(series_id: str, start: str, session: requests.Session | None = None) -> pd.DataFrame:
    http = session or requests.Session()
    api_key = os.environ.get("FRED_API_KEY")
    if api_key:
        resp = http.get(
            API_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return parse_api_json(resp.json(), series_id)
    resp = http.get(CSV_URL, params={"id": series_id, "cosd": start}, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_csv(resp.text, series_id)


def fetch_many(series_ids: list[str], start: str) -> tuple[pd.DataFrame, list[str]]:
    """Descarga varias series; devuelve (datos, series_que_fallaron)."""
    frames, failed = [], []
    with requests.Session() as http:
        for sid in series_ids:
            try:
                frames.append(fetch_series(sid, start, http))
            except Exception as exc:  # noqa: BLE001
                log.warning("FRED %s fallo: %s", sid, exc)
                failed.append(sid)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return data, failed
