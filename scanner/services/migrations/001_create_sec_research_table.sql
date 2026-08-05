-- SEC Research Analysis Table
-- Run: python3 scanner/services/sec_research.py --upcoming 14 (auto-creates table)
-- Or manually: psql -U swingtrader -d swingtrader -f scanner/services/migrations/001_create_sec_research_table.sql

CREATE TABLE IF NOT EXISTS tbl_sec_research_analysis (
    id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    earnings_date DATE,
    filing_date DATE,
    filing_type VARCHAR(10),
    score INTEGER,
    rank_in_run INTEGER,
    analysis_data JSONB,
    board_comments TEXT,
    sources JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_sec_research_ticker ON tbl_sec_research_analysis(ticker);
CREATE INDEX IF NOT EXISTS idx_sec_research_run_id ON tbl_sec_research_analysis(run_id);
CREATE INDEX IF NOT EXISTS idx_sec_research_earnings ON tbl_sec_research_analysis(earnings_date);
CREATE INDEX IF NOT EXISTS idx_sec_research_score ON tbl_sec_research_analysis(score DESC);
