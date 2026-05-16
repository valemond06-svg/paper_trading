"""
Tests di verifica locale per BTC_4H_BREAKOUT_DAILY_REGIME.

Esegui con:
    python -m pytest tests/test_btc4h_strategy.py -v

Oppure direttamente:
    python tests/test_btc4h_strategy.py
"""

import sys
from pathlib import Path

# Aggiungi la root del progetto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

from strategies.btc_4h_breakout_daily_regime import (
    generate_signal,
    is_regime_bullish,
    STRATEGY_NAME,
    BREAKOUT_PERIOD,
    ATR_PERIOD,
    SMA_DAILY_PERIOD,
    ATR_STOP_MULT,
    ATR_TP_MULT,
    RISK_PER_TRADE,
)


# ---------------------------------------------------------------------------
# Helpers: costruttori di DataFrame sintetici
# ---------------------------------------------------------------------------

def _make_4h_df(n: int = 300, last_breakout: bool = False) -> pd.DataFrame:
    """Genera barre 4h sintetiche. Se last_breakout=True la chiusura finale
    supera il rolling_high(20) precedente."""
    rng  = np.random.default_rng(42)
    base = 50_000.0
    closes = base + np.cumsum(rng.normal(0, 200, n))
    highs  = closes + rng.uniform(50, 300, n)
    lows   = closes - rng.uniform(50, 300, n)
    opens  = closes + rng.normal(0, 100, n)

    if last_breakout:
        # Forza l'ultima close sopra il massimo delle 20 barre precedenti
        closes[-1] = highs[-22:-2].max() + 500.0
        highs[-1]  = closes[-1] + 100.0

    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})


def _make_daily_df_bullish(n: int = 250) -> pd.DataFrame:
    """Daily con trend rialzista: l'ultima close > SMA200."""
    closes = np.linspace(30_000, 70_000, n)  # trend monotono crescente
    highs  = closes + 500.0
    lows   = closes - 500.0
    opens  = closes - 100.0
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})


def _make_daily_df_bearish(n: int = 250) -> pd.DataFrame:
    """Daily con trend ribassista: l'ultima close < SMA200."""
    closes = np.linspace(70_000, 30_000, n)  # trend monotono decrescente
    highs  = closes + 500.0
    lows   = closes - 500.0
    opens  = closes + 100.0
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})


# ---------------------------------------------------------------------------
# Test 1: regime filter blocca entry in mercato bearish
# ---------------------------------------------------------------------------

def test_regime_filter_blocks_bearish():
    daily_bear = _make_daily_df_bearish()
    log_msgs   = []
    result     = is_regime_bullish(daily_bear, log_fn=log_msgs.append)

    assert result is False, "Il regime filter deve bloccare in mercato bearish"
    assert any("strategy inactive by regime" in m for m in log_msgs), (
        "Deve loggare 'strategy inactive by regime' in regime bearish"
    )
    print("[PASS] test_regime_filter_blocks_bearish")


# ---------------------------------------------------------------------------
# Test 2: regime filter permette entry in mercato bullish
# ---------------------------------------------------------------------------

def test_regime_filter_allows_bullish():
    daily_bull = _make_daily_df_bullish()
    result     = is_regime_bullish(daily_bull)
    assert result is True, "Il regime filter deve passare in mercato bullish"
    print("[PASS] test_regime_filter_allows_bullish")


# ---------------------------------------------------------------------------
# Test 3: nessun segnale se regime bearish (generate_signal ritorna None)
# ---------------------------------------------------------------------------

def test_no_signal_in_bearish_regime():
    df_4h      = _make_4h_df(last_breakout=True)
    daily_bear = _make_daily_df_bearish()
    signal     = generate_signal(df_4h, daily_bear, equity=10_000.0)
    assert signal is None, (
        "generate_signal deve ritornare None in regime bearish "
        "anche se c'è un breakout 4h valido"
    )
    print("[PASS] test_no_signal_in_bearish_regime")


# ---------------------------------------------------------------------------
# Test 4: segnale generato correttamente in regime bullish + breakout
# ---------------------------------------------------------------------------

def test_signal_generated_in_bullish_regime():
    df_4h      = _make_4h_df(last_breakout=True)
    daily_bull = _make_daily_df_bullish()
    equity     = 10_000.0
    log_msgs   = []
    signal     = generate_signal(df_4h, daily_bull, equity, log_fn=log_msgs.append)

    assert signal is not None, "Deve generare un segnale con breakout + regime bullish"
    assert signal["strategy"] == STRATEGY_NAME
    assert signal["regime"] is True
    assert any("BREAKOUT SIGNAL" in m for m in log_msgs)
    print("[PASS] test_signal_generated_in_bullish_regime")
    return signal, equity


# ---------------------------------------------------------------------------
# Test 5: il sizing non supera il 1% di risk
# ---------------------------------------------------------------------------

def test_sizing_respects_1pct_risk():
    df_4h      = _make_4h_df(last_breakout=True)
    daily_bull = _make_daily_df_bullish()
    equity     = 10_000.0
    signal     = generate_signal(df_4h, daily_bull, equity)

    assert signal is not None
    expected_risk  = equity * RISK_PER_TRADE         # 100.0
    actual_risk    = signal["quantity"] * (signal["entry_price"] - signal["stop_price"])
    tolerance      = 1e-6

    assert abs(actual_risk - expected_risk) < tolerance, (
        f"Risk amount atteso={expected_risk:.4f}, effettivo={actual_risk:.4f}. "
        "Il sizing deve rispettare esattamente il 1% risk."
    )
    print(f"[PASS] test_sizing_respects_1pct_risk | risk_amount={actual_risk:.4f}")


# ---------------------------------------------------------------------------
# Test 6: stop e target calcolati con i moltiplicatori ATR corretti
# ---------------------------------------------------------------------------

def test_stop_and_target_atr_levels():
    df_4h      = _make_4h_df(last_breakout=True)
    daily_bull = _make_daily_df_bullish()
    signal     = generate_signal(df_4h, daily_bull, equity=10_000.0)

    assert signal is not None
    entry = signal["entry_price"]
    stop  = signal["stop_price"]
    tp    = signal["take_profit"]
    atr   = signal["atr"]

    expected_stop = entry - ATR_STOP_MULT * atr
    expected_tp   = entry + ATR_TP_MULT  * atr
    tol = 1e-6

    assert abs(stop - expected_stop) < tol, (
        f"Stop atteso={expected_stop:.4f}, effettivo={stop:.4f}. "
        f"Deve essere entry - {ATR_STOP_MULT} x ATR"
    )
    assert abs(tp - expected_tp) < tol, (
        f"TP atteso={expected_tp:.4f}, effettivo={tp:.4f}. "
        f"Deve essere entry + {ATR_TP_MULT} x ATR"
    )
    rr = (tp - entry) / (entry - stop)
    print(
        f"[PASS] test_stop_and_target_atr_levels "
        f"| R:R={rr:.2f} stop_dist={entry-stop:.2f} tp_dist={tp-entry:.2f}"
    )


# ---------------------------------------------------------------------------
# Test 7: dati insufficienti non crashano
# ---------------------------------------------------------------------------

def test_insufficient_data_returns_none():
    df_short   = _make_4h_df(n=10)
    daily_bull = _make_daily_df_bullish()
    signal     = generate_signal(df_short, daily_bull, equity=10_000.0)
    assert signal is None, "Con dati insufficienti deve ritornare None senza eccezioni"
    print("[PASS] test_insufficient_data_returns_none")


# ---------------------------------------------------------------------------
# Main runner (senza pytest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print(f"Test suite: {STRATEGY_NAME}")
    print("=" * 60)
    test_regime_filter_blocks_bearish()
    test_regime_filter_allows_bullish()
    test_no_signal_in_bearish_regime()
    test_signal_generated_in_bullish_regime()
    test_sizing_respects_1pct_risk()
    test_stop_and_target_atr_levels()
    test_insufficient_data_returns_none()
    print("=" * 60)
    print("All tests passed.")
    print("=" * 60)
