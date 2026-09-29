-- Ranking de momentum a 3 meses (63 sesiones) de emisoras de la BMV.
WITH px AS (
    SELECT p.ticker, u.name, p.date, p.adj_close,
           lag(p.adj_close, 63) OVER (PARTITION BY p.ticker ORDER BY p.date) AS adj_close_3m,
           row_number() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
    FROM prices p
    JOIN universe u USING (ticker)
    WHERE u.market = 'BMV'
)
SELECT ticker, name, date,
       round(adj_close, 2) AS precio,
       round(100 * (adj_close / adj_close_3m - 1), 2) AS rend_3m_pct
FROM px
WHERE rn = 1 AND adj_close_3m IS NOT NULL
ORDER BY rend_3m_pct DESC
LIMIT 20;
