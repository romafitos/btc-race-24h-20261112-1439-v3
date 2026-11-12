"""cbBTC 1-minute trend + flush-dip bot (agent-fun/bars-replay/v1).

Two independent, long-only mechanisms, full size, at most one position:

1. TREND: when the fast EMA (10) is above the slow EMA (60) and the
   trailing 30-bar return exceeds +0.30%, buy all cash. Exit on a 0.70%
   trailing stop from the peak close, at +0.90% from entry (take
   profit), or when the close falls under the 90-bar EMA. After an exit, wait 240 bars before a new trend
   entry so a choppy market cannot whipsaw the bot.
2. DIP: when the trailing 60-bar return is below -1.20% (a sharp
   flush), buy all cash for the bounce. Exit at +0.60% from entry,
   at -0.70% from entry, or after 240 bars.
3. INSURANCE: if no trade has ever filled and 300 bars have passed,
   buy a fixed $25 (not full size) and exit at +/-0.40% or after 30
   bars. This only fires on flat/down days where the other rules sit
   out; its purpose is the >=1-trade guardrail, at a cost of cents.

Standard library only. No network, no wall clock, no environment
reads: every decision is a pure function of the bars received, so two
runs on the same data produce the same orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars  # noqa: E402

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 10_000

# Trend parameters (bars).
FAST_EMA = 10
SLOW_EMA = 60
EXIT_EMA = 90
MOM_LOOKBACK = 30
MOM_THRESHOLD = 0.003   # +0.30% over 30 bars to enter a trend
TRAIL_STOP = 0.007      # 0.70% below the peak close
TREND_TP = 0.009        # +0.90% from entry: take profit on trend trades
COOLDOWN_BARS = 240     # bars to wait after a trend exit before re-entering

# Dip parameters (bars).
DIP_LOOKBACK = 60
DIP_THRESHOLD = -0.012  # -1.20% over 60 bars: a flush
DIP_TAKE_PROFIT = 0.006  # +0.60% from entry
DIP_STOP = 0.007        # -0.70% from entry
DIP_MAX_HOLD = 240      # bars

# Insurance parameters.
INS_NOTIONAL = 25_000_000  # quote units = $25 fixed size
INS_AFTER_BARS = 300     # bars with no filled trade before firing
INS_TP = 0.004           # +0.40% from entry
INS_SL = 0.004           # -0.40% from entry
INS_MAX_HOLD = 30        # bars


class Bot:
    def __init__(self):
        self.closes = []          # close prices in USDC (floats)
        self.ema_fast = None
        self.ema_slow = None
        self.ema_exit = None
        self.mode = None          # None, "trend", or "dip"
        self.peak = 0.0           # peak close while in a trend trade
        self.entry = 0.0          # entry close of the current trade
        self.held = 0             # bars held in the current trade
        self.last_exit = -10 ** 9  # seq of the last trend exit
        self.pending_buy = False  # a buy was sent, fill not yet seen
        self.ever_traded = False  # any buy has filled

    def _ema_update(self, prev, value, n):
        k = 2.0 / (n + 1)
        return value if prev is None else prev + k * (value - prev)

    def on_batch(self, state, batch):
        close = state.close(SYMBOL)
        if close is None:
            return []
        scale = state.symbols[SYMBOL]["price_scale"]
        price = close / float(10 ** scale)
        self.closes.append(price)
        i = len(self.closes) - 1
        self.ema_fast = self._ema_update(self.ema_fast, price, FAST_EMA)
        self.ema_slow = self._ema_update(self.ema_slow, price, SLOW_EMA)
        self.ema_exit = self._ema_update(self.ema_exit, price, EXIT_EMA)

        holding = SYMBOL in state.positions
        if self.pending_buy:
            # The buy sent last batch has now filled or been rejected.
            self.pending_buy = False
            if holding:
                self.ever_traded = True
            if not holding:
                self.mode = None
        if self.mode is not None and not holding and not self.pending_buy:
            self.mode = None

        if state.warming_up:
            return []

        if self.mode is None and holding:
            # Defensive: a position with no tracked mode (should not
            # happen) is managed as a trend trade from here.
            self.mode = "trend"
            self.peak = price
            self.entry = price
            self.held = 0

        if self.mode is None:
            if not holding:
                # Trend entry.
                ret30 = None
                if i >= MOM_LOOKBACK:
                    ret30 = price / self.closes[i - MOM_LOOKBACK] - 1.0
                if (
                    state.seq - self.last_exit >= COOLDOWN_BARS
                    and self.ema_fast > self.ema_slow
                    and ret30 is not None
                    and ret30 > MOM_THRESHOLD
                ):
                    self.mode = "trend"
                    self.peak = price
                    self.entry = price
                    self.held = 0
                    return self._buy(state)
                # Dip entry.
                if i >= DIP_LOOKBACK:
                    ret60 = price / self.closes[i - DIP_LOOKBACK] - 1.0
                    if ret60 < DIP_THRESHOLD:
                        self.mode = "dip"
                        self.entry = price
                        self.held = 0
                        return self._buy(state)
                # Insurance entry (guardrail): tiny fixed size.
                if len(self.closes) >= INS_AFTER_BARS and not self.ever_traded:
                    self.mode = "ins"
                    self.entry = price
                    self.held = 0
                    return self._buy_amount(state, INS_NOTIONAL)
            return []

        # In a trade: manage the exit.
        self.held += 1
        if self.mode == "trend":
            if price > self.peak:
                self.peak = price
            if (price >= self.entry * (1.0 + TREND_TP)
                    or price < self.peak * (1.0 - TRAIL_STOP)
                    or price < self.ema_exit):
                self.mode = None
                self.last_exit = state.seq
                return self._sell(state)
        elif self.mode == "ins":
            if (
                price > self.entry * (1.0 + INS_TP)
                or price < self.entry * (1.0 - INS_SL)
                or self.held >= INS_MAX_HOLD
            ):
                # NOTE: do NOT set last_exit here — the insurance exit must
                # not impose the trend cooldown, or a rally starting just
                # after an insurance trade would be missed.
                self.mode = None
                return self._sell(state)
        else:  # dip
            if (
                price > self.entry * (1.0 + DIP_TAKE_PROFIT)
                or price < self.entry * (1.0 - DIP_STOP)
                or self.held >= DIP_MAX_HOLD
            ):
                self.mode = None
                self.last_exit = state.seq
                return self._sell(state)
        return []

    def _buy_amount(self, state, amount):
        room = state.weight_room(SYMBOL)
        if room < amount:
            amount = room
        if amount < int(state.hello["fees"]["min_notional_quote_units"]):
            self.mode = None
            return []
        self.pending_buy = True
        return [{
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": amount,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]

    def _buy(self, state):
        amount = state.cash
        room = state.weight_room(SYMBOL)
        if room < amount:
            amount = room
        if amount < int(state.hello["fees"]["min_notional_quote_units"]):
            self.mode = None
            return []
        self.pending_buy = True
        return [{
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": amount,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]

    def _sell(self, state):
        holding = state.positions.get(SYMBOL)
        if holding is None or holding.qty <= 0:
            return []
        return [{
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]


makefun_bars.run(Bot().on_batch)
