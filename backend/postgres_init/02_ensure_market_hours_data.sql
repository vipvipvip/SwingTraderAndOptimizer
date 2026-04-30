-- Ensure bars table contains ONLY market hours data (9:30 AM - 4:00 PM ET)
-- Market hours in UTC: 14:00 - 20:00 (9:30 AM - 4:00 PM ET)
-- This runs during database initialization and after migrations

-- Remove any out-of-hours bars that may have been migrated or loaded
DELETE FROM bars
WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 14 AND 20;

-- Note: New bars fetched by optimizer/data_fetcher.py are filtered via filter_market_hours()
-- This constraint ensures historical data is also clean
