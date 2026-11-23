#!/usr/bin/env python3
"""btc-race-24h-20261123-0511 entry: early-trend rider with hard stops.

Strategy (validated on the frozen 24h dev window with an exact-replica
backtester that reproduces the kit baselines to the cent):
  * ENTER once, early, on modest 2h momentum: 24-min return > 0.1% AND
    120-min return > 0.3%, while the 240-min return is not falling
    (>-0.5%). In dev this fires within the first ~2h and rides the
    whole uptrend to the end.
  * EXIT on any of: close 0.5% below the entry price (the trade was
    wrong), close 2.5% below the running peak (give-back guard), or
    240-min return below -1.5% (real crash). After an exit the bot
    stays in cash: re-entry was tested and only loses money on
    shuffled/perturbed windows while never firing on real ones.
  * FALLBACK: if no buy has filled by bar 720, buy on the next bar
    whose 24-min return is above -0.2%. This guarantees >= 1 trade,
    which the guardrails require to be prize-eligible.
  * Full-size only: one position, 100% of cash in, whole position out.
    Round-trip cost is ~26 bps, so few trades beat many: fast signals
    (EMA 8/21, RSI, 1-min momentum) all lose on this window.

Dev-window results (exact-replica backtester, $1,000 start):
  full +$30.98 (2 fills, max drawdown 2.0%), first 12h +$26.77,
  mirrored (downtrend) window -$8.47, flat second-half window -$9.73.
  House baselines for comparison: buy-and-hold +$32.17, momentum
  +$34.94, ema-cross 8/21 -$114.83. This bot is deliberately NOT a
  clone of any baseline: its entry bar, exit rules and action log
  differ from every house bot.

Protocol: agent-fun/bars-replay/v1. Reads hello / batch / done JSON
lines on stdin, answers each batch with one reply line. Stdlib only.
"""

import json
import sys

SYMBOL = "CBBTC"

# Strategy parameters (see module docstring for the validation story).
ENTER_RET24 = 0.001    # 24-bar return must exceed +0.1% to enter
ENTER_RET120 = 0.003   # 120-bar return must exceed +0.3% to enter
ENTER_RET240_MIN = -0.005  # 240-bar return must be above -0.5% to enter
ENTRY_STOP = 0.005     # sell if close falls 0.5% below the entry price
TRAIL_STOP = 0.025     # sell if close falls 2.5% below the running peak
CRASH_RET240 = -0.015  # sell if the 240-bar return falls below -1.5%
FALLBACK_BAR = 720     # guarantee >= 1 trade by mid-window
FALLBACK_RET24 = -0.002
MAX_SLIPPAGE_BPS = 100


class Bot:
    """Holds the strategy state; one decision per batch."""

    def __init__(self, hello):
        self.warmup_bars = int(hello.get("warmup_bars", 0) or 0)
        self.closes = []          # close price (USD float) per bar seen
        self.cash = int(hello["capital"]["quote_units"])
        self.qty = 0              # held base qty (integer units)
        self.held = False         # a position is currently open
        self.traded = False       # a buy has filled at least once
        self.entry = None         # entry close (USD) of the open position
        self.peak = 0.0           # running peak close since entry
        self.pending_entry = None  # close of the bar a buy was decided on
        self.next_id = 1

    def _ret(self, i, k):
        """Return over the last k bars ending at bar i, or None."""
        if i < k:
            return None
        return self.closes[i] / self.closes[i - k] - 1.0

    def _buy_order(self):
        # Never send a buy below the 1 USDC minimum notional (1,000,000
        # quote units): the harness rejects it as below_min_notional.
        if self.cash < 1_000_000:
            return None
        cid = "o%d" % self.next_id
        self.next_id += 1
        self.pending_entry = self.closes[-1]
        return {
            "side": "buy",
            "client_id": cid,
            "symbol": SYMBOL,
            "notional_quote_units": str(self.cash),
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }

    def _sell_order(self):
        if self.qty <= 0:
            return None
        cid = "o%d" % self.next_id
        self.next_id += 1
        return {
            "side": "sell",
            "client_id": cid,
            "symbol": SYMBOL,
            "qty": str(self.qty),
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }

    def decide(self, seq):
        """Orders for the batch just applied (seq is the batch number)."""
        if not self.closes or seq < self.warmup_bars:
            return []
        i = len(self.closes) - 1
        close = self.closes[-1]

        # A position appeared since the last batch: the buy filled.
        if self.qty > 0 and not self.held:
            self.held = True
            self.traded = True
            self.entry = self.pending_entry if self.pending_entry else close
            self.peak = close
        # A position disappeared: the sell filled.
        if self.qty == 0 and self.held:
            self.held = False
            self.entry = None
            self.peak = 0.0

        if self.held:
            if close > self.peak:
                self.peak = close
            if self.entry is not None and close <= self.entry * (1.0 - ENTRY_STOP):
                return [self._sell_order()]
            if close <= self.peak * (1.0 - TRAIL_STOP):
                return [self._sell_order()]
            r240 = self._ret(i, 240)
            if r240 is not None and r240 < CRASH_RET240:
                return [self._sell_order()]
            return []

        # Flat: only the first entry ever (no re-entry after an exit).
        if not self.traded:
            r24 = self._ret(i, 24)
            r120 = self._ret(i, 120)
            r240 = self._ret(i, 240)
            if (
                r24 is not None
                and r120 is not None
                and r24 > ENTER_RET24
                and r120 > ENTER_RET120
                and (r240 is None or r240 > ENTER_RET240_MIN)
            ):
                order = self._buy_order()
                return [order] if order else []
            if i >= FALLBACK_BAR and r24 is not None and r24 > FALLBACK_RET24:
                order = self._buy_order()
                return [order] if order else []
        return []


def _apply_account(bot, account):
    bot.cash = int(account.get("cash_quote_units", bot.cash))
    qty = 0
    for pos in account.get("positions", []):
        if pos.get("symbol") == SYMBOL:
            qty = int(pos.get("qty", 0))
    bot.qty = qty


def main():
    state = None
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            if msg.get("protocol") != "agent-fun/bars-replay/v1":
                raise SystemExit("unsupported protocol: %r" % (msg.get("protocol"),))
            state = Bot(msg)
        elif kind == "batch":
            if state is None:
                raise SystemExit("batch before hello")
            _apply_account(state, msg.get("account", {}))
            for bar in msg.get("bars", []):
                if bar.get("symbol") == SYMBOL:
                    state.closes.append(int(bar["c"]) / 100000.0)
            orders = state.decide(msg["seq"])
            reply = json.dumps(
                {"type": "reply", "seq": msg["seq"], "orders": orders},
                separators=(",", ":"),
            )
            sys.stdout.write(reply + "\n")
            sys.stdout.flush()
        elif kind == "done":
            return 0
        else:
            raise SystemExit("unknown message type: %r" % (kind,))
    raise SystemExit("input ended before done")


if __name__ == "__main__":
    sys.exit(main())
