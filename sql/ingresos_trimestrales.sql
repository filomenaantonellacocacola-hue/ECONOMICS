-- Ingresos, utilidad neta y margen neto trimestrales de una emisora (millones, moneda de reporte).
SELECT period_end,
       round(max(value) FILTER (WHERE item = 'TotalRevenue') / 1e6, 1) AS ingresos_mm,
       round(max(value) FILTER (WHERE item = 'NetIncomeCommonStockholders') / 1e6, 1) AS utilidad_neta_mm,
       round(100 * max(value) FILTER (WHERE item = 'NetIncomeCommonStockholders')
                 / max(value) FILTER (WHERE item = 'TotalRevenue'), 2) AS margen_neto_pct
FROM financials
WHERE ticker = 'WALMEX.MX' AND statement = 'income' AND freq = 'Q'
GROUP BY period_end
ORDER BY period_end DESC;
