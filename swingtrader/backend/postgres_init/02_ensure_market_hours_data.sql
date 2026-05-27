-- Ensure bars table contains ONLY market hours data (9:30 AM - 4:30 PM ET)
-- Market hours in UTC: 13:00 - 20:00 (9:30 AM - 4:30 PM ET)
-- Hourly bars include: 13:30, 14:30, 15:30, 16:30, 17:30, 18:30, 19:30, 20:30 UTC
-- This runs during database initialization and after migrations

-- Remove any out-of-hours bars that may have been migrated or loaded
DELETE FROM bars
WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 13 AND 20;

-- Note: New bars fetched by optimizer/data_fetcher.py are filtered via filter_market_hours()
-- This constraint ensures historical data is also clean
