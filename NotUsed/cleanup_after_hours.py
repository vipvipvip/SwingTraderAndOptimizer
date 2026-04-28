#!/usr/bin/env python3
"""Delete all after-hours bars from database (keep only 9:30 AM - 4:00 PM ET)"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

db_path = 'optimized_params/strategy_params.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 60)
print("CLEANUP: Removing After-Hours Bars")
print("=" * 60)

# Get current bar count
cursor.execute("SELECT COUNT(*) FROM bars")
total_before = cursor.fetchone()[0]
print(f"\nTotal bars before cleanup: {total_before}")

# Get bars outside market hours (before 9:30 AM or after 4:00 PM ET)
cursor.execute('''
    SELECT COUNT(*) FROM bars
    WHERE (
        strftime('%H:%M', timestamp) < '09:30' OR
        strftime('%H:%M', timestamp) > '16:00'
    )
''')
after_hours_count = cursor.fetchone()[0]
print(f"After-hours bars to delete: {after_hours_count}")

if after_hours_count > 0:
    # Delete after-hours bars
    cursor.execute('''
        DELETE FROM bars
        WHERE (
            strftime('%H:%M', timestamp) < '09:30' OR
            strftime('%H:%M', timestamp) > '16:00'
        )
    ''')
    conn.commit()
    print(f"✓ Deleted {cursor.rowcount} after-hours bars")

# Verify
cursor.execute("SELECT COUNT(*) FROM bars")
total_after = cursor.fetchone()[0]
print(f"\nTotal bars after cleanup: {total_after}")
print(f"Bars removed: {total_before - total_after}")

# Show breakdown by ticker
cursor.execute('''
    SELECT t.symbol, COUNT(*) as bar_count
    FROM bars b
    JOIN tickers t ON b.ticker_id = t.id
    GROUP BY t.symbol
    ORDER BY t.symbol
''')

print(f"\nBars per ticker:")
for symbol, count in cursor.fetchall():
    print(f"  {symbol}: {count}")

conn.close()
print("\n✓ Cleanup complete")
