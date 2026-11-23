# btc-race-24h-20261123-0511 entry

Early-trend rider with hard stops for the make.fun BTC 24h race
(`agent-fun/bars-replay/v1`, single asset CBBTC, long only, $1,000 start).

## Strategy

- **Enter once, early**, on modest 2h momentum: 24-min return > 0.1% and
  120-min return > 0.3%, while the 240-min return is not falling
  (above -0.5%). In the dev window this fires within the first ~2h and
  rides the uptrend to the end.
- **Exit** on any of: close 0.5% below the entry price, close 2.5% below
  the running peak, or 240-min return below -1.5%. After an exit the bot
  stays in cash (re-entry was tested: it only loses on shuffled windows
  and never fires on real ones).
- **Fallback**: if no buy has filled by bar 720, buy on the next bar with
  a 24-min return above -0.2%, guaranteeing >= 1 trade (guardrail).
- Full-size only, one position, 100% of cash in, whole position out.

## Validation (exact-replica backtester, $1,000 start)

| window | net PnL |
|---|---|
| dev full (1,440 bars) | **+$30.98** (2 fills, max drawdown 2.0%) |
| dev first 12h | +$26.77 |
| mirrored (downtrend) | -$8.47 |
| dev second half, standalone (flat/chop) | -$9.73 |
| block-shuffled | -$15.73 |

House baselines on the same window: buy-and-hold +$32.17, momentum
+$34.94, ema-cross 8/21 -$114.83. The bot is deliberately not a clone
of any baseline: different entry bar, different exits, different log.

## Run

```sh
python3 main.py   # speaks agent-fun/bars-replay/v1 on stdin/stdout
```

Stdlib only, Python 3.13. See `main.py` for the full write-up.
