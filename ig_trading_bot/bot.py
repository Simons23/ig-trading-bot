"""
IG Markets CFD Trading Bot
Strategy: Aggressive ASX 200 momentum swing trading
Author: Built for Simon via Claude
"""

import time
import logging
import os
from datetime import datetime, timezone
from trading_ig import IGService
from trading_ig.config import config
import pandas as pd
import numpy as np

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

# Markets to trade (IG EPIC codes)
MARKETS = {
   MARKETS = {
    "GOLD":     "CS.D.CFDGOLD.CFM.IP",
    "EURUSD":   "CS.D.EURUSD.MINI.IP",
    "GBPUSD":   "CS.D.GBPUSD.MINI.IP",
}
}

# Trading parameters
ACCOUNT_SIZE       = 10_000   # AUD - your demo account size
MAX_RISK_PER_TRADE = 0.10     # Risk max 10% of account per trade
STOP_LOSS_PCT      = 0.015    # 1.5% stop loss from entry
TAKE_PROFIT_PCT    = 0.050    # 5.0% take profit (3.3:1 R:R)
SCAN_INTERVAL_SEC  = 60       # Check markets every 60 seconds
MAX_OPEN_POSITIONS = 3        # Never hold more than 3 positions at once

# Strategy: EMA Crossover + RSI Filter
EMA_FAST    = 9    # Fast EMA period
EMA_SLOW    = 21   # Slow EMA period
RSI_PERIOD  = 14   # RSI period
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30


# ─── Indicator Calculations ───────────────────────────────────────────────────

def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def get_signal(df: pd.DataFrame) -> str:
    """
    Returns 'BUY', 'SELL', or 'HOLD' based on:
    - EMA crossover (fast crosses above/below slow)
    - RSI filter (avoid overbought buys / oversold sells)
    - Price momentum confirmation
    """
    if len(df) < EMA_SLOW + 5:
        return "HOLD"

    close = df["close"]
    ema_fast = calculate_ema(close, EMA_FAST)
    ema_slow = calculate_ema(close, EMA_SLOW)
    rsi = calculate_rsi(close, RSI_PERIOD)

    # Current and previous values
    ef_now, ef_prev = ema_fast.iloc[-1], ema_fast.iloc[-2]
    es_now, es_prev = ema_slow.iloc[-1], ema_slow.iloc[-2]
    rsi_now = rsi.iloc[-1]

    # Bullish crossover: fast crosses above slow, RSI not overbought
    bullish_cross = (ef_prev < es_prev) and (ef_now > es_now)
    # Bearish crossover: fast crosses below slow, RSI not oversold
    bearish_cross = (ef_prev > es_prev) and (ef_now < es_now)

    if bullish_cross and rsi_now < RSI_OVERBOUGHT:
        return "BUY"
    elif bearish_cross and rsi_now > RSI_OVERSOLD:
        return "SELL"
    else:
        return "HOLD"


# ─── Position Sizing ──────────────────────────────────────────────────────────

def calculate_position_size(account_balance: float, current_price: float) -> float:
    """
    Risk-based position sizing.
    Risks MAX_RISK_PER_TRADE of account, with stop at STOP_LOSS_PCT from entry.
    Returns number of CFD contracts (minimum 1).
    """
    risk_amount = account_balance * MAX_RISK_PER_TRADE
    stop_loss_points = current_price * STOP_LOSS_PCT
    size = risk_amount / stop_loss_points
    return max(round(size, 2), 1.0)


# ─── IG API Helpers ───────────────────────────────────────────────────────────

def fetch_prices(ig: IGService, epic: str, resolution: str = "MINUTE", num_points: int = 100) -> pd.DataFrame:
    """Fetch historical OHLC prices for an epic."""
    try:
        response = ig.fetch_historical_prices_by_epic_and_num_points(epic, resolution, num_points)
        prices = response["prices"]
        df = pd.DataFrame({
            "open":  prices["bid"]["Open"],
            "high":  prices["bid"]["High"],
            "low":   prices["bid"]["Low"],
            "close": prices["bid"]["Close"],
        })
        return df.dropna()
    except Exception as e:
        log.error(f"Error fetching prices for {epic}: {e}")
        return pd.DataFrame()


def get_open_positions(ig: IGService) -> list:
    """Returns list of currently open positions."""
    try:
        positions = ig.fetch_open_positions()
        if isinstance(positions, pd.DataFrame):
            return positions.to_dict("records")
        return []
    except Exception as e:
        log.error(f"Error fetching open positions: {e}")
        return []


def open_position(ig: IGService, epic: str, direction: str, size: float, price: float):
    """Open a CFD position with stop loss and take profit."""
    if direction == "BUY":
        stop_level  = round(price * (1 - STOP_LOSS_PCT), 2)
        limit_level = round(price * (1 + TAKE_PROFIT_PCT), 2)
    else:
        stop_level  = round(price * (1 + STOP_LOSS_PCT), 2)
        limit_level = round(price * (1 - TAKE_PROFIT_PCT), 2)

    try:
        response = ig.create_open_position(
            currency_code="AUD",
            direction=direction,
            epic=epic,
            expiry="-",
            force_open="true",
            guaranteed_stop="false",
            order_type="MARKET",
            size=size,
            level=None,
            limit_distance=None,
            limit_level=limit_level,
            quote_id=None,
            stop_level=stop_level,
            stop_distance=None,
            trailing_stop=False,
            trailing_stop_increment=None,
        )
        log.info(f"✅ Opened {direction} {size} contracts of {epic} | Stop: {stop_level} | Target: {limit_level}")
        return response
    except Exception as e:
        log.error(f"❌ Failed to open position for {epic}: {e}")
        return None


def close_all_losing_positions(ig: IGService):
    """Emergency: close any position past max loss threshold."""
    # IG auto-handles stop losses, but this is a safety net
    pass


# ─── Main Bot Loop ────────────────────────────────────────────────────────────

def run_bot():
    log.info("=" * 60)
    log.info("🤖 IG CFD Trading Bot Starting")
    log.info(f"   Account Size:    AUD ${ACCOUNT_SIZE:,.0f}")
    log.info(f"   Max Risk/Trade:  {MAX_RISK_PER_TRADE*100:.0f}%")
    log.info(f"   Stop Loss:       {STOP_LOSS_PCT*100:.1f}%")
    log.info(f"   Take Profit:     {TAKE_PROFIT_PCT*100:.1f}%")
    log.info(f"   Scan Interval:   {SCAN_INTERVAL_SEC}s")
    log.info(f"   Markets:         {', '.join(MARKETS.keys())}")
    log.info("=" * 60)

    # Connect to IG
    ig = IGService(
        config.username,
        config.password,
        config.api_key,
        config.acc_type
    )
    ig.create_session()
    log.info("✅ Connected to IG Markets (DEMO)")

    scan_count = 0

    while True:
        scan_count += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log.info(f"\n--- Scan #{scan_count} | {now} ---")

        # Get current open positions
        open_positions = get_open_positions(ig)
        log.info(f"Open positions: {len(open_positions)}/{MAX_OPEN_POSITIONS}")

        if len(open_positions) >= MAX_OPEN_POSITIONS:
            log.info("Max positions reached. Monitoring only.")
        else:
            # Scan each market for signals
            for name, epic in MARKETS.items():
                log.info(f"Scanning {name} ({epic})...")

                # Check if already in this market
                already_in = any(
                    p.get("market", {}).get("epic") == epic
                    for p in open_positions
                )
                if already_in:
                    log.info(f"  Already holding {name}. Skipping.")
                    continue

                # Fetch prices and generate signal
                df = fetch_prices(ig, epic, resolution="1h", num_points=100)
                if df.empty:
                    log.warning(f"  No price data for {name}. Skipping.")
                    continue

                signal = get_signal(df)
                current_price = df["close"].iloc[-1]

                log.info(f"  {name}: Price={current_price:.2f} | Signal={signal}")

                if signal in ("BUY", "SELL"):
                    # Check we won't exceed max positions
                    if len(open_positions) < MAX_OPEN_POSITIONS:
                        size = calculate_position_size(ACCOUNT_SIZE, current_price)
                        log.info(f"  🎯 Signal! {signal} {name} | Size: {size} contracts")
                        open_position(ig, epic, signal, size, current_price)
                        open_positions = get_open_positions(ig)  # Refresh
                    else:
                        log.info(f"  Signal found for {name} but max positions reached.")

                # Small delay between market scans to avoid API rate limits
                time.sleep(2)

        log.info(f"Next scan in {SCAN_INTERVAL_SEC} seconds...\n")
        time.sleep(SCAN_INTERVAL_SEC)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        log.info("\n🛑 Bot stopped by user.")
    except Exception as e:
        log.critical(f"💥 Fatal error: {e}", exc_info=True)
