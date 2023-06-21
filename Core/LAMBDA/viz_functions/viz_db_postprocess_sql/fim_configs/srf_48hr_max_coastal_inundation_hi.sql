DROP TABLE IF EXISTS publish.srf_48hr_max_coastal_inundation_hi;

SELECT
    inundation.*,
    to_char(now()::timestamp without time zone, 'YYYY-MM-DD HH24:MI:SS UTC') AS update_time
INTO publish.srf_48hr_max_coastal_inundation_hi
FROM ingest.srf_48hr_max_coastal_inundation_hi AS inundation;
