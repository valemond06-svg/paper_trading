"""
live_runner_btc4h.py
---------------------
Runner live per la strategia BTC_4H_BREAKOUT_DAILY_REGIME.

Usa price_feed_adapter per scaricare i dati OHLCV da Binance,
attiva il segnale via strategies.btc_4h_breakout_daily_regime
e delega tutta la gestione dello stato a PaperTradingBot.

Avvio:
    python live_runner_btc4h.py

Note di sicurezza:
    - le chiavi API (se usate in futuro per live trading) restano in .env
    - questo runner NON logga token o chiavi
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from paper_trading_executor import PaperTradingBot, PLANJSON, MAX_OPEN_TRADES
from strategies.btc_4h_breakout_daily_regime import (
    STRATEGY_NAME,
    generate_signal,
    is_regime_bullish,
    RISK_PER_TRADE,
    ATR_STOP_MULT,
    ATR_TP_MULT,
)

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
SYMBOL       = "BTCUSDT"
TF_4H        = "4h"
TF_1D        = "1d"
BARLIMIT_4H  = 300   # ~50 giorni di storia 4h
BARLIMIT_1D  = 250   # ~1 anno di storia daily
POLL_SECONDS = 60    # frequenza di polling (secondi)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fetch OHLCV (adattato al price_feed_adapter esistente)
# ---------------------------------------------------------------------------

def _fetch_ohlcv(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """
    Scarica dati OHLCV da Binance public REST (no API key).
    Restituisce DataFrame con colonne: open high low close volume.
    """
    import urllib.request, json
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = json.loads(resp.read())

    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Costruisce il row compatibile con PaperTradingBot.open_position()
# ---------------------------------------------------------------------------

def _build_plan_row(signal: dict, target_weight: float = 0.95) -> dict:
    """
    Traduce il segnale della strategia nel formato 'row' atteso dall'executor.
    stop e target vengono passati come override separati; il bot usa
    open_position() con i valori calcolati dalla strategia.
    """
    return {
        "asset"          : signal["asset"],
        "timeframe"      : signal["timeframe"],
        "strategy"       : signal["strategy"],
        "target_weight"  : target_weight,
        "risk_per_trade" : RISK_PER_TRADE,
        # campi legacy richiesti da symbol_for_row()
        "fast"           : 0,
        "slow"           : 0,
        "regime"         : "daily_sma200",
        "symbol"         : STRATEGY_NAME,
    }


# ---------------------------------------------------------------------------
# Override stop/tp sull'executor usando i valori ATR calcolati
# ---------------------------------------------------------------------------

def _open_with_atr_levels(bot: PaperTradingBot, signal: dict) -> None:
    """
    Apre la posizione e poi sovrascrive stop_price e take_profit
    con i valori ATR calcolati dalla strategia (invece delle % fisse del bot).
    """
    row   = _build_plan_row(signal)
    price = signal["entry_price"]
    pos   = bot.open_position(row, price)

    if pos is None:
        return

    # Override con i livelli ATR validati
    pos.stop_price  = signal["stop_price"]
    pos.take_profit = signal["take_profit"]
    bot.save_state()

    bot.log(
        f"{STRATEGY_NAME} | position opened with ATR levels "
        f"stop={pos.stop_price:.2f} tp={pos.take_profit:.2f} "
        f"atr={signal['atr']:.2f}"
    )


# ---------------------------------------------------------------------------
# Loop principale
# ---------------------------------------------------------------------------

def run_once(bot: PaperTradingBot) -> None:
    """Esegue un singolo ciclo di valutazione."""
    try:
        df_4h    = _fetch_ohlcv(SYMBOL, TF_4H, BARLIMIT_4H)
        df_daily = _fetch_ohlcv(SYMBOL, TF_1D, BARLIMIT_1D)
    except Exception as exc:
        bot.log(f"{STRATEGY_NAME} | fetch error: {exc}")
        return

    # Aggiorna il prezzo corrente nell'executor
    current_price = float(df_4h["close"].iloc[-1])
    bot.run_cycle({SYMBOL: current_price})

    # Controlla se già in posizione
    if STRATEGY_NAME in bot.positions:
        return

    if len(bot.positions) >= MAX_OPEN_TRADES:
        return

    # Genera segnale (include il controllo regime)
    signal = generate_signal(df_4h, df_daily, bot.equity, log_fn=bot.log)
    if signal is None:
        return

    _open_with_atr_levels(bot, signal)


def main() -> None:
    bot = PaperTradingBot(PLANJSON)
    bot.load_state()
    bot.log(f"live_runner_btc4h started | strategy={STRATEGY_NAME}")

    while True:
        try:
            run_once(bot)
        except KeyboardInterrupt:
            bot.log("live_runner_btc4h stopped by user")
            break
        except Exception as exc:
            bot.log(f"live_runner_btc4h unhandled error: {exc}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
