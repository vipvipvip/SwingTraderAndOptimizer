"""Shared ETF P&L table formatting for Slack (runner.py) and terminal (show_picks.py)."""


def etf_table_lines(top_n, score_detail, entry_prices):
    """Return list of formatted ETF P&L table lines.

    top_n: list of dicts with 'symbol', 'score', 'freshness', 'gap_w'
    score_detail: dict[symbol] -> {'close': float, ...}
    entry_prices: dict[symbol] -> {'price': float, 'date': str}
    """
    lines = [
        f'{"#":<3} {"Ticker":<8} {"Score":>5} {"Entry $":>8} {"Now $":>8} {"P&L %":>7} {"Fresh":>7}',
        f'{"-"*3} {"-"*8} {"-"*5} {"-"*8} {"-"*8} {"-"*7} {"-"*7}',
    ]
    for i, t in enumerate(top_n, 1):
        sym = t['symbol']
        close = score_detail.get(sym, {}).get('close', 0)
        ep = entry_prices.get(sym, {}).get('price', 0)
        ep_str = f'${ep:.2f}' if ep else 'N/A'
        close_str = f'${close:.2f}' if close else 'N/A'
        ret = f'{(close - ep) / ep * 100:+.2f}%' if ep and close else 'N/A'
        days_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
        lines.append(
            f'{i:<3} {sym:<8} {t["score"]:>5.1f} '
            f'{ep_str:>8} {close_str:>8} {ret:>7} {days_str:>7}'
        )
    return lines
