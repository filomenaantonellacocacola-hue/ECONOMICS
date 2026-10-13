-- Acciones de la BMV ordenadas por P/U, con rentabilidad, dividendos y puntajes (unidades normalizadas).
SELECT ticker, name, sector,
       round(mkt_cap_mxn_bn, 1) AS mkt_cap_mmm_mxn,
       round(pe, 1) AS pe,
       round(pb, 2) AS p_vl,
       round(ev_ebitda, 1) AS ev_ebitda,
       round(roe_pct, 1) AS roe_pct,
       round(div_yield_pct, 2) AS div_yield_pct,
       round(target_upside_pct, 1) AS potencial_pct,
       score_value, score_quality,
       fund_date AS corte
FROM equity_snapshot
WHERE market = 'BMV' AND asset_type = 'stock' AND pe > 0
ORDER BY pe ASC;
