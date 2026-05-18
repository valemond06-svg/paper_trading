"""
Strategy: BTC_4H_BREAKOUT_DAILY_REGIME
---------------------------------------
Timeframe operativo : 4h
Regime filter       : daily close > SMA200 daily
Entry               : close 4h > rolling_high(20 barre 4h)
Stop                : entry - 1.5 × ATR14(4h)
Target              : entry + 2.5 × ATR14(4h)
Risk per trade      : 1% equity
Fee                 : 0.05% per lato + slippage 0.05% per lato

Parametri validati con walk-forward (5/6 finestre positive):
  PF medio ~1.44  |  Sharpe medio ~1.0  |  MaxDD medio ~8.7%

VINCOLI:
  - Nessuna entry se daily_close <= SMA200 daily
  - Non introduce indicatori aggiuntivi rispetto a quelli testati
  - Non altera il risk management globale dell'executor
"""

from __future__ import annotations

from typing import Optional
import pandas as pd

STRATEGY_NAME = "BTC_4H_BREAKOUT_DAILY_REGIME"

# Parametri validati — non modificare senza nuovo walk-forward
BREAKOUT_PERIOD    = 20    # barre 4h per rolling_high
ATR_PERIOD         = 14    # ATR su 4h
ATR_STOP_MULT      = 1.5   # moltiplicatore ATR per stop
ATR_TP_MULT        = 2.5   # moltiplicatore ATR per target
SMA_DAILY_PERIOD   = 200   # SMA daily per filtro regime
RISK_PER_TRADE     = 0.01  # 1% equity


# ---------------------------------------------------------------------------
# Indicatori
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True Range medio su `period` barre. Richiede colonne high/low/close."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev  = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev).abs(),
        (low  - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _rolling_high(df: pd.DataFrame, period: int = BREAKOUT_PERIOD) -> pd.Series:
    """Rolling max delle `period` barre precedenti (shift 1 per non lookahead)."""
    return df["high"].shift(1).rolling(period).max()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# ---------------------------------------------------------------------------
# Regime filter
# ---------------------------------------------------------------------------

def is_regime_bullish(
    daily_df: pd.DataFrame,
    log_fn=None,
) -> bool:
    """
    Ritorna True se l'ultima daily close > SMA200 daily.
    Logga il motivo del blocco se log_fn è fornita.
    """
    if daily_df is None or len(daily_df) < SMA_DAILY_PERIOD:
        if log_fn:
            log_fn(f"{STRATEGY_NAME} | regime_check: insufficient daily data")
        return False

    sma200 = _sma(daily_df["close"], SMA_DAILY_PERIOD)
    last_close = float(daily_df["close"].iloc[-1])
    last_sma   = float(sma200.iloc[-1])

    if pd.isna(last_sma):
        if log_fn:
            log_fn(f"{STRATEGY_NAME} | regime_check: SMA200 NaN")
        return False

    bullish = last_close > last_sma
    if not bullish and log_fn:
        log_fn(
            f"{STRATEGY_NAME} | strategy inactive by regime | "
            f"daily_close={last_close:.2f} SMA200={last_sma:.2f}"
        )
    return bullish


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def generate_signal(
    df_4h: pd.DataFrame,
    daily_df: pd.DataFrame,
    equity: float,
    log_fn=None,
) -> Optional[dict]:
    """
    Analizza le ultime barre e ritorna un dict con i parametri del trade
    oppure None se non ci sono condizioni di entry.

    Parametri ritornati:
      {
        "strategy"    : STRATEGY_NAME,
        "asset"       : "BTCUSDT",
        "timeframe"   : "4h",
        "entry_price" : float,
        "stop_price"  : float,
        "take_profit" : float,
        "quantity"    : float,
        "risk_amount" : float,
        "atr"         : float,
        "regime"      : True,
      }
    """
    # --- 1. Regime filter ---
    if not is_regime_bullish(daily_df, log_fn):
        return None

    # --- 2. Breakout signal ---
    if df_4h is None or len(df_4h) < BREAKOUT_PERIOD + ATR_PERIOD + 1:
        if log_fn:
            log_fn(f"{STRATEGY_NAME} | insufficient 4h data")
        return None

    atr_series     = _atr(df_4h)
    rolling_high   = _rolling_high(df_4h)
    last_close     = float(df_4h["close"].iloc[-1])
    last_high_ref  = float(rolling_high.iloc[-1])
    last_atr       = float(atr_series.iloc[-1])

    if pd.isna(last_high_ref) or pd.isna(last_atr) or last_atr <= 0:
        if log_fn:
            log_fn(f"{STRATEGY_NAME} | breakout_check: NaN in indicators")
        return None

    if last_close <= last_high_ref:
        # Nessun breakout: non loggare per non spammare
        return None

    # --- 3. Sizing con risk 1% ---
    risk_amount  = equity * RISK_PER_TRADE
    entry_price  = last_close                          # market order al close
    stop_price   = entry_price - ATR_STOP_MULT * last_atr
    take_profit  = entry_price + ATR_TP_MULT  * last_atr
    stop_dist    = entry_price - stop_price

    if stop_dist <= 0:
        if log_fn:
            log_fn(f"{STRATEGY_NAME} | sizing error: stop_dist <= 0")
        return None

    quantity = risk_amount / stop_dist

    if log_fn:
        log_fn(
            f"{STRATEGY_NAME} | BREAKOUT SIGNAL "
            f"entry={entry_price:.2f} stop={stop_price:.2f} tp={take_profit:.2f} "
            f"ATR={last_atr:.2f} qty={quantity:.6f} risk_amount={risk_amount:.2f}"
        )

    return {
        "strategy"   : STRATEGY_NAME,
        "asset"      : "BTCUSDT",
        "timeframe"  : "4h",
        "entry_price": entry_price,
        "stop_price" : stop_price,
        "take_profit": take_profit,
        "quantity"   : quantity,
        "risk_amount": risk_amount,
        "atr"        : last_atr,
        "regime"     : True,
    }
