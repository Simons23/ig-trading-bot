"""
IG Markets CFD Trading Bot - v2
Strategy: Aggressive momentum swing trading
Auto-discovers working markets and resolutions
Author: Built for Simon via Claude
"""

import time
import logging
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

# Candidate markets to try (in priority order)
# The bot will test each one and only trade the ones that work
CANDIDATE_MARKETS = {
    "ASX200":    "IX.D.ASX.CFD.IP",
    "GOLD":      "CS.D.CFDGOLD.CFM.IP",
    "OIL":       "CS.D.CFDSB.CFM.IP",
    "ASX200_b":  "IX.D.ASX.IFM.IP",
    "OIL_b":     "CS.D.CRUDE.CFM.IP",
    "SILVER":    "CS.D.CFDSILVER.CFM.IP",
    "COPPER":    "CS.D.COPPER.CFM.IP",
}

# Resolutions to try (in order of preference)
RESOLUTIONS_TO_TRY = ["1h", "H", "HOUR", "DAY", "D", "4h", "30Min", "15Min"]

# Trading parameters
ACCOUNT_SIZE       = 10_000
MAX_RISK_PER_TRADE = 0.10
STOP_LOSS_PCT      = 0.015
TAKE_PROFIT_PCT    = 0.050
SCAN_INTERVAL_SEC  = 60
MAX_OPEN_POSITIONS = 3
MIN_CANDLES        = 30   # Minimum candles needed for indicators

# Strategy parameters
EMA_FAST       = 9
EMA_SLOW       = 21
RSI_PERIOD     = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30


# ─── Market Discovery ─────────────────────────────────────────────────────────

def discover_working_markets(ig: IGService) -> dict:
    """
    Tests each candidate market with each resolution.
    Returns a dict of {name: (epic, resolution)} for markets that work.
    """
    log.info("🔍 Discovering available markets and resolutions...")
    working = {}

    for name, epic in CANDIDATE_MARKETS.items():
        # Skip alternate epics if we already found a working one for this market
        base_name = name.replace("_b", "")
        if base_name in working:
            continue

        for resolution in RESOLUTIONS_TO_TRY:
            try:
                log.info(f"  Testing {name} ({epic}) @ {resolution}...")
                response = ig.fetch_historical_prices_by_epic_and_num_points(
                    epic, resolution, 5
                )
                prices = response["prices"]
                df = pd.DataFrame({
                    "close": prices["bid"]["Close"]
                }).dropna()

                if len(df) >= 3:
                    log.info(f"  ✅ {base_name} works! Epic={epic}, Resolution={resolution}")
                    working[base_name] = (epic, resolution)
                    break
                else:
                    log.info(f"  ⚠️  {name} @ {resolution}: too few data points")

            except Exception as e:
                log.info(f"  ❌ {name} @ {resolution}: {str(e)[:60]}")

            time.sleep(1)  # Be gentle with the API

    log.info(f"\n✅ Found {len(working)} working market(s): {list(working.keys())}")
    return working


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
    if len(df) < EMA_SLOW + 5:
        return "HOLD"

    close = df["close"]
    ema_fast = calculate_ema(close, EMA_FAST)
    ema_slow = calculate_ema(close, EMA_SLOW)
    rsi = calculate_rsi(close, RSI_PERIOD)

    ef_now, ef_prev = ema_fast.iloc[-1], ema_fast.iloc[-2]
    es_now, es_prev = ema_slow.iloc[-1], ema_slow.iloc[-2]
    rsi_now = rsi.iloc[-1]

    bullish_cross = (ef_prev < es_prev) and (ef_now > es_now)
    bearish_cross = (ef_prev > es_prev) and (ef_now < es_now)

    if bullish_cross and rsi_now < RSI_OVERBOUGHT:
        return "BUY"
    elif bearish_cross and rsi_now > RSI_OVERSOLD:
        return "SELL"
    return "HOLD"


# ─── Position Sizing ──────────────────────────────────────────────────────────

def calculate_position_size(account_balance: float, current_price: float) -> float:
    risk_amount = account_balance * MAX_RISK_PER_TRADE
    stop_loss_points = current_price * STOP_LOSS_PCT
    size = risk_amount / stop_loss_points
    return max(round(size, 2), 1.0)


# ─── IG API Helpers ───────────────────────────────────────────────────────────

def fetch_prices(ig: IGService, epic: str, resolution: str, num_points: int = 100) -> pd.DataFrame:
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
    try:
        positions = ig.fetch_open_positions()
        if isinstance(positions, pd.DataFrame):
            return positions.to_dict("records")
        return []
    except Exception as e:
        log.error(f"Error fetching open positions: {e}")
        return []


def open_position(ig: IGService, epic: str, direction: str, size: float, price: float):
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


# ─── Main Bot Loop ────────────────────────────────────────────────────────────

def run_bot():
    log.info("=" * 60)
    log.info("🤖 IG CFD Trading Bot v2 Starting")
    log.info(f"   Account Size:    AUD ${ACCOUNT_SIZE:,.0f}")
    log.info(f"   Max Risk/Trade:  {MAX_RISK_PER_TRADE*100:.0f}%")
    log.info(f"   Stop Loss:       {STOP_LOSS_PCT*100:.1f}%")
    log.info(f"   Take Profit:     {TAKE_PROFIT_PCT*100:.1f}%")
    log.info(f"   Scan Interval:   {SCAN_INTERVAL_SEC}s")
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

    # Auto-discover working markets
    working_markets = discover_working_markets(ig)

    if not working_markets:
        log.critical("❌ No working markets found. Check your IG API access and try again.")
        return

    log.info(f"\n🎯 Trading the following markets: {list(working_markets.keys())}")

    # Rediscover markets every 6 hours in case something changes
    last_discovery = time.time()
    REDISCOVER_INTERVAL = 6 * 60 * 60

    scan_count = 0

    while True:
        # Periodically re-check available markets
        if time.time() - last_discovery > REDISCOVER_INTERVAL:
            log.info("🔄 Re-checking available markets...")
            working_markets = discover_working_markets(ig)
            last_discovery = time.time()

        scan_count += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log.info(f"\n--- Scan #{scan_count} | {now} ---")

        open_positions = get_open_positions(ig)
        log.info(f"Open positions: {len(open_positions)}/{MAX_OPEN_POSITIONS}")

        if len(open_positions) >= MAX_OPEN_POSITIONS:
            log.info("Max positions reached. Monitoring only.")
        else:
            for name, (epic, resolution) in working_markets.items():
                log.info(f"Scanning {name} ({epic}) @ {resolution}...")

                already_in = any(
                    p.get("market", {}).get("epic") == epic
                    for p in open_positions
                )
                if already_in:
                    log.info(f"  Already holding {name}. Skipping.")
                    continue

                df = fetch_prices(ig, epic, resolution, num_points=100)
                if df.empty:
                    log.warning(f"  No price data for {name}. Skipping.")
                    continue

                signal = get_signal(df)
                current_price = df["close"].iloc[-1]
                log.info(f"  {name}: Price={current_price:.2f} | Signal={signal}")

                if signal in ("BUY", "SELL"):
                    if len(open_positions) < MAX_OPEN_POSITIONS:
                        size = calculate_position_size(ACCOUNT_SIZE, current_price)
                        log.info(f"  🎯 Signal! {signal} {name} | Size: {size} contracts")
                        open_position(ig, epic, signal, size, current_price)
                        open_positions = get_open_positions(ig)
                    else:
                        log.info(f"  Signal found for {name} but max positions reached.")

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
