"""Portfolio execution harness — the BACKTEST-ONLY half of the split.

Ownership boundary (see emasma_core.py):
  emasma_core  = strategy decisions (score, settled bar, ranking)  -> live + backtest
  harness.py   = portfolio mechanics (fills, sizing, cost, metrics) -> backtest only
  runner.py    = orchestration (timers, Slack, orders)             -> live only

Why sizing/fills are not shared with live: live sends real market orders and
takes whatever the book gives. Modelling next-day close fills is a *simulation*
choice, not a strategy rule. Forcing live to import a fill simulator would be a
lie, and forcing the backtest to import live's order plumbing would make runs
depend on a broker session. The things that must match — which names are picked
and when — already match, because both come from emasma_core.

Constants are imported from mtf/config.py, never redefined here.
"""
import math

import config

COST_PER_SIDE = config.COST_PER_TRADE
INITIAL_CAPITAL = config.INITIAL_CAPITAL


class Convention:
    """The fill convention, named and switchable instead of implicit.

    This is the single largest source of variance in the results. Two choices
    below move the SAME signal on the SAME data by ~165 percentage points, so
    they are pinned here, documented in FILL_CONVENTION.md, and exercised by
    regression_check.py.

    PENDING: none of these yet reproduce the published P20w figures
    (+364.27% / -19.2% DD). The published convention is not yet identified.
    Until it is, P20w absolute figures are NOT pinnable and are excluded from
    the regression gate.
    """

    # when the book is pulled back to equal weight
    #   'weekly'   - every bar (rebalances constantly; high order count)
    #   'on-change'- only when the set of held names changes
    rebalance_trigger = 'weekly'

    # which price the fill uses
    #   'next-close' - close of the first trading day after the decision
    #   'next-open'  - open of that day (not modelled yet; needs open series)
    price_point = 'next-close'

    # how "orders" is counted in the metrics
    #   'rebalance-orders' - one per symbol per rebalance
    #   'trade-legs'       - only legs that fully close or open
    order_counting = 'rebalance-orders'

    def __str__(self):
        return f"{self.rebalance_trigger}/{self.price_point}/{self.order_counting}"


CONVENTION = Convention()


def should_rebalance(convention, held, prev_held):
    """Apply the convention's rebalance trigger."""
    if convention.rebalance_trigger == 'weekly':
        return True
    return held != prev_held


def equal_weight_targets(equity, symbols):
    """Equal-weight notional per name. Mirrors live EQUAL_WEIGHT sizing.

    Live trims every overweight held name and tops up every underweight
    in-play name to equity/len(in_play), so held winners stop drifting
    untrimmed. Same target math here.
    """
    if not symbols:
        return {}
    per = equity / len(symbols)
    return {s: per for s in symbols}


def apply_cost(notional):
    return notional * COST_PER_SIDE


def metrics(equity_curve, periods_per_year=52):
    """equity_curve: list of (date, equity), oldest first.

    Returns the standard sheet used across the repo's backtests.
    """
    if len(equity_curve) < 2:
        return {}
    start_eq = equity_curve[0][1]
    end_eq = equity_curve[-1][1]
    total_ret = (end_eq / start_eq - 1) * 100 if start_eq else 0.0

    years = (equity_curve[-1][0] - equity_curve[0][0]).days / 365.25
    cagr = ((end_eq / start_eq) ** (1 / years) - 1) * 100 if years > 0 and start_eq > 0 and end_eq > 0 else 0.0

    peak, max_dd = equity_curve[0][1], 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100)
    max_dd = -max_dd  # negative, matches repo convention

    calmar = (cagr / abs(max_dd)) if max_dd else 0.0
    ups = sum(1 for i in range(1, len(equity_curve)) if equity_curve[i][1] > equity_curve[i - 1][1])
    return {
        'total_return_pct': round(total_ret, 2),
        'cagr_pct': round(cagr, 2),
        'max_dd_pct': round(max_dd, 1),
        'calmar': round(calmar, 2),
        'periods_up_pct': round(ups / (len(equity_curve) - 1) * 100, 1),
    }


class Sim:
    """Weekly-rebalanced equal-weight book. Signals in, executed positions out.

    next_fill_date: date of the decision; fills happen at the close of the next
    available trading date, matching live (decide on settled weekly bar, trade
    during the following session). price_fn(symbol, date) -> close or None.
    """

    def __init__(self, capital=INITIAL_CAPITAL, cost=COST_PER_SIDE, price_fn=None):
        self.cash = capital
        self.capital = capital
        self.pos = {}          # symbol -> shares
        self.cost = cost
        self.price_fn = price_fn
        self.orders = 0
        self.equity_curve = []
        self.avg_invested = []

    def equity(self, date):
        return self.cash + sum(
            sh * (self.price_fn(s, date) or 0.0) for s, sh in self.pos.items()
        )

    def rebalance(self, date, symbols):
        eq = self.equity(date)
        targets = equal_weight_targets(eq, symbols)

        # sell first so cash is available to fund buys
        for s in list(self.pos):
            if s not in targets:
                px = self.price_fn(s, date)
                if px:
                    self.cash += self.pos.pop(s) * px * (1 - self.cost)
                    self.orders += 1

        for s, target in targets.items():
            px = self.price_fn(s, date)
            if not px:
                continue
            cur = self.pos.get(s, 0) * px
            if target > cur:
                buy_dollars = (target - cur) / (1 + self.cost)
                if buy_dollars > 0 and buy_dollars <= self.cash:
                    shares = buy_dollars / px
                    self.cash -= buy_dollars * (1 + self.cost)
                    self.pos[s] = self.pos.get(s, 0) + shares
                    self.orders += 1
            elif cur > target:
                sell_sh = (cur - target) / px
                if sell_sh > 0:
                    self.pos[s] -= sell_sh
                    self.cash += sell_sh * px * (1 - self.cost)
                    self.orders += 1

        invested = sum(sh * (self.price_fn(s, date) or 0.0) for s, sh in self.pos.items())
        self.avg_invested.append(invested / eq * 100 if eq else 0.0)
        self.equity_curve.append((date, self.equity(date)))

    def finish(self):
        out = metrics(self.equity_curve)
        out['orders'] = self.orders
        out['avg_invested_pct'] = round(sum(self.avg_invested) / len(self.avg_invested), 1) if self.avg_invested else 0.0
        return out