-- Emisoras de la BMV ordenadas por P/U, con rentabilidad y dividendos (requiere fundamentales).
SELECT f.ticker, u.name, f.sector,
       round(f.marketCap / 1e9, 1) AS mkt_cap_miles_mill,
       round(f.trailingPE, 1) AS pe,
       round(f.priceToBook, 2) AS p_vl,
       round(f.enterpriseToEbitda, 1) AS ev_ebitda,
       round(100 * f.returnOnEquity, 1) AS roe_pct,
       round(f.dividendYield, 2) AS div_yield,
       f.date AS corte
FROM fundamentals_latest f
JOIN universe u USING (ticker)
WHERE u.market = 'BMV' AND f.trailingPE > 0
ORDER BY pe ASC;
