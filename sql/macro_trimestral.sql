-- Tablero trimestral: crecimiento del PIB, inflacion, desempleo y tasas (EE.UU. y Mexico).
-- Cambia macro_quarterly por macro_monthly, macro_semiannual o macro_annual para otra frecuencia.
SELECT period_label AS periodo,
       name AS serie,
       round(value, 2) AS valor,
       round(pct_yoy, 2) AS var_anual_pct,
       round(chg_yoy, 2) AS cambio_anual,
       is_partial AS parcial
FROM macro_quarterly
WHERE series_id IN ('GDPC1', 'CPIAUCSL', 'UNRATE', 'DFEDTARU', 'DGS10', 'SF61745', 'SP1')
  AND period >= current_date - INTERVAL 3 YEAR
ORDER BY series_id, period DESC;
