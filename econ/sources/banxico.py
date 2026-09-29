"""Series del Sistema de Informacion Economica (SIE) de Banxico.

Requiere ``BANXICO_TOKEN`` (gratis: https://www.banxico.org.mx/SieAPIRest/service/v1/token).
Sin token, se omite sin error.
"""
from __future__ import annotations

import logging
import os
from datetime import date

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/{ids}/datos/{start}/{end}"
TIMEOUT = 60


def parse_response(payload: dict) -> pd.DataFrame:
    rows = []
    for serie in payload.get("bmx", {}).get("series", []):
        sid = serie.get("idSerie")
        for obs in serie.get("datos", []) or []:
            rows.append({"series_id": sid, "date": obs.get("fecha"), "value": obs.get("dato")})
    df = pd.DataFrame(rows, columns=["series_id", "date", "value"])
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y")
    df["value"] = pd.to_numeric(df["value"].astype(str).str.replace(",", ""), errors="coerce").astype("float64")
    df = df.dropna(subset=["value"])
    df.insert(0, "source", "BANXICO")
    return df[["source", "series_id", "date", "value"]].reset_index(drop=True)


def fetch_many(series_ids: list[str], start: str) -> tuple[pd.DataFrame, list[str]]:
    token = os.environ.get("BANXICO_TOKEN")
    if not series_ids:
        return pd.DataFrame(), []
    if not token:
        log.info("BANXICO_TOKEN no definido; se omiten series de Banxico")
        return pd.DataFrame(), list(series_ids)
    url = BASE_URL.format(ids=",".join(series_ids), start=start, end=date.today().isoformat())
    try:
        resp = requests.get(url, headers={"Bmx-Token": token, "Accept": "application/json"}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = parse_response(resp.json())
    except Exception as exc:  # noqa: BLE001
        log.warning("Banxico fallo: %s", exc)
        return pd.DataFrame(), list(series_ids)
    failed = sorted(set(series_ids) - set(data["series_id"].unique()))
    return data, failed
