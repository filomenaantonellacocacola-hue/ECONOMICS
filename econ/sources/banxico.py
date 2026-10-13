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

API_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1"
BASE_URL = API_URL + "/series/{ids}/datos/{start}/{end}"
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


def search(query: str, session: requests.Session | None = None) -> list[dict]:
    """Busca series en el catalogo publico del SIE (no usa token).

    Es el buscador de la pagina del catalogo, no la API documentada: funciona mejor
    con pocas palabras ("agregado monetario", "M4").
    """
    http = session or requests.Session()
    resp = http.get(f"{API_URL}/cat/series", params={"q": query}, timeout=TIMEOUT)
    resp.raise_for_status()
    seen, out = set(), []
    for r in resp.json().get("bmx", {}).get("resultados", []) or []:
        sid = r.get("idSerie")
        if sid and sid not in seen:
            seen.add(sid)
            out.append({"id": sid, "descripcion": " ".join(str(r.get("texto", "")).split())})
    return out


def series_info(series_id: str, session: requests.Session | None = None) -> dict:
    """Ficha de una serie del catalogo publico (titulo, periodicidad, unidad, fechas)."""
    http = session or requests.Session()
    resp = http.get(f"{API_URL}/cat/series/{series_id}", timeout=TIMEOUT)
    resp.raise_for_status()
    series = resp.json().get("bmx", {}).get("series") or []
    return {k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in (series[0] if series else {}).items()}


def search_catalog(queries: list[str], max_info: int = 150) -> dict:
    """Busca varias consultas y agrega la ficha de cada serie encontrada (hasta ``max_info``)."""
    result: dict = {}
    infos = 0
    with requests.Session() as http:
        for q in queries:
            hits = search(q, http)
            for hit in hits:
                if infos >= max_info:
                    break
                try:
                    hit["ficha"] = series_info(hit["id"], http)
                except Exception as exc:  # noqa: BLE001
                    hit["ficha"] = {"error": str(exc)}
                infos += 1
            result[q] = hits
    return result
