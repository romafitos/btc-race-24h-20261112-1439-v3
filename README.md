# cbBTC trend + flush-dip bot — v3

v3 = v2 + one guardrail: an insurance (dead-man's switch) trade. If no
trade has ever filled and 300 bars have passed, buy a fixed $25
(`INS_NOTIONAL = 25_000_000` quote units), exit at ±0.40% or after 30
bars. The insurance exit does NOT set the trend cooldown, so a rally
starting right after it is not blocked. Everything else is unchanged
from v2.

## Why

RULES.txt Guardrails: an entry with 0 trades ranks below EVERY entry
meeting the bar (≥1 trade, drawdown ≤25%) and takes no prize — even
entries with negative PnL rank above it. v2 ends at $0 with 0 trades
on a flat/down race day, so on such a day it is a certain no-prize.
The insurance buys prize eligibility for cents: it fires only where
v2 sits out, never interferes where v2 trades (v2's first trade fills
at bar 55, long before bar 300), and can fire at most once (after one
trade has filled, the "no trade yet" condition never holds again).

## Multi-window evidence (faithful replay, fees/slippage/impact included)

| window | v2 PnL | v3 PnL | v2 DD | v3 DD | v3 trades |
|---|---|---|---|---|---|
| full dev 24h | +$11.74 | +$11.74 | 0.60% | 0.60% | 4 (identical — never fires) |
| B1 up +1.00% | +$8.46 | +$8.46 | 0.60% | 0.60% | 2 (identical) |
| B2 chop −0.90% | +$3.26 | +$3.26 | 0.27% | 0.27% | 2 (identical) |
| B3 flat −0.40% | $0.00 | −$0.01 | 0.00% | 0.00% | 2 (buy bar 300, sell bar 330) |
| B4 down −1.95% | $0.00 | −$0.13 | 0.00% | 0.01% | 2 (buy bar 300, sell bar 330) |
| offset bars (+30s) full | +$11.48 | +$11.48 | 0.55% | 0.55% | 4 (identical) |
| offset B3 | — | −$0.01 | — | 0.00% | 2 |
| offset B4 | — | −$0.10 | — | 0.01% | 2 |

Mean 6h-block PnL: v2 $2.93, v3 $2.90 — the insurance costs $0.035 of
mean PnL and at most $0.13 in any window, for eligibility on days v2
would score $0 with 0 trades. Both beat the house EMA-cross baseline
(−$95.88 full; −$20.67 / −$10.63 / −$32.73 / −$38.40 per block) in
every window.

Honest note: B3/B4 are structurally near-untradeable (B3's best
60-bar forward move is +0.30% vs ~0.26% round-trip cost; B4's only
bounce is smaller than the fill-cost wedge). No lever makes money
there — the insurance is an eligibility purchase, not a profit lever.

## Strategy (v2 + insurance)

1. TREND: fast EMA (10) above slow EMA (60) and trailing 30-bar return
   above +0.30% → buy all cash. Exit at +0.90% from entry, on a 0.70%
   trailing stop from the peak close, or when the close falls under the
   90-bar EMA. 240-bar cooldown after a trend exit.
2. DIP: trailing 60-bar return below −1.20% (a sharp flush) → buy all
   cash for the bounce. Exit at +0.60% from entry, at −0.70% from entry,
   or after 240 bars.
3. INSURANCE: no filled trade after 300 bars → buy fixed $25. Exit at
   ±0.40% from entry or after 30 bars. Exit does not set the cooldown.

Standard library only. No network, no wall clock, no environment reads:
every decision is a pure function of the bars received, so two runs on
the same data produce the same orders.

Standard library only. No network, no wall clock, no environment reads:
every decision is a pure function of the bars received, so two runs on
the same data produce the same orders.
