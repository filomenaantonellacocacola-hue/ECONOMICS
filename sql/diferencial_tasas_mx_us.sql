-- Diferencial mensual entre la tasa objetivo de Banxico y la de la Fed (requiere BANXICO_TOKEN).
WITH mensual AS (
    SELECT date_trunc('month', date) AS mes, series_id, last(value ORDER BY date) AS valor
    FROM macro
    WHERE series_id IN ('SF61745', 'DFEDTARU')
    GROUP BY ALL
)
SELECT mes,
       max(valor) FILTER (WHERE series_id = 'SF61745') AS banxico,
       max(valor) FILTER (WHERE series_id = 'DFEDTARU') AS fed,
       banxico - fed AS diferencial_pp
FROM mensual
GROUP BY mes
HAVING banxico IS NOT NULL AND fed IS NOT NULL
ORDER BY mes DESC
LIMIT 36;
