#!/usr/bin/env python3
"""Delete all after-hours bars from PostgreSQL database (keep only 9:30 AM - 4:00 PM ET)

This script removes bars outside regular market hours from the bars table.
Used for cleaning historical data after migration or to fix data integrity issues.

Market hours: 9:30 AM - 4:00 PM ET = 14:00 - 20:00 UTC (since bars are stored in UTC)
"""
import psycopg2
from datetime import datetime

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'database': 'swingtrader',
    'user': 'swingtrader',
    'password': 'swingtrader_dev_password'
}

def cleanup_after_hours():
    """Remove all bars outside market hours (9:30 AM - 4:00 PM ET)"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print("=" * 60)
        print("CLEANUP: Removing After-Hours Bars (PostgreSQL)")
        print("=" * 60)

        # Get current bar count
        cursor.execute("SELECT COUNT(*) FROM bars")
        total_before = cursor.fetchone()[0]
        print(f"\nTotal bars before cleanup: {total_before}")

        # Get bars outside market hours
        # Market hours in UTC: 13:00 - 20:00 (9:30 AM - 4:30 PM ET)
        # Hourly bars: 13:30, 14:30, 15:30, 16:30, 17:30, 18:30, 19:30, 20:30
        cursor.execute('''
            SELECT COUNT(*) FROM bars
            WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 13 AND 20
        ''')
        after_hours_count = cursor.fetchone()[0]
        print(f"After-hours bars to delete: {after_hours_count}")

        if after_hours_count > 0:
            # Delete after-hours bars
            cursor.execute('''
                DELETE FROM bars
                WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 13 AND 20
            ''')
            conn.commit()
            print(f"✓ Deleted {cursor.rowcount} after-hours bars")
        else:
            print("✓ No after-hours bars found - database is clean")

        # Verify
        cursor.execute("SELECT COUNT(*) FROM bars")
        total_after = cursor.fetchone()[0]
        print(f"\nTotal bars after cleanup: {total_after}")
        if total_before > total_after:
            print(f"Bars removed: {total_before - total_after}")

        # Show breakdown by hour (should only see 14-20)
        cursor.execute('''
            SELECT EXTRACT(HOUR FROM timestamp)::INT as hour, COUNT(*) as bar_count
            FROM bars
            GROUP BY hour
            ORDER BY hour
        ''')

        print(f"\nBars by hour (UTC):")
        hours = cursor.fetchall()
        if hours:
            for hour, count in hours:
                print(f"  {hour:02d}:00 - {hour:02d}:59: {count} bars")
        else:
            print("  No bars in database")

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
        return True

    except Exception as e:
        print(f"✗ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    cleanup_after_hours()
