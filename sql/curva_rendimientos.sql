-- Ultima curva de Treasuries de EE.UU. y spreads clave.
SELECT series_id, name, date, value
FROM macro_latest
WHERE source = 'FRED'
  AND series_id IN ('DFEDTARU', 'DGS3MO', 'DGS2', 'DGS10', 'DGS30', 'T10Y2Y', 'T10Y3M')
ORDER BY CASE series_id
    WHEN 'DFEDTARU' THEN 0 WHEN 'DGS3MO' THEN 1 WHEN 'DGS2' THEN 2
    WHEN 'DGS10' THEN 3 WHEN 'DGS30' THEN 4 ELSE 5 END;
