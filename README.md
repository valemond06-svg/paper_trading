# Paper Trading Bot

Bot di paper trading su Python per testare strategie quantitative su BTCUSDT  
prima di passare al live trading reale.

---

## Strategia attiva: BTC_4H_BREAKOUT_DAILY_REGIME

L'unica strategia live è quella che ha mostrato edge sufficiente nel walk-forward:

| Parametro | Valore |
|-----------|--------|
| Timeframe operativo | 4h |
| Filtro regime | `daily close > SMA200 daily` |
| Entry signal | `close 4h > rolling_high(20)` |
| Stop loss | `entry − 1.5 × ATR14(4h)` |
| Take profit | `entry + 2.5 × ATR14(4h)` |
| Risk per trade | **1% equity** |
| Fee totale | 0.10% (0.05% × 2 lati) |
| Slippage totale | 0.10% (0.05% × 2 lati) |

### Walk-forward summary
- Finestre positive: ~5/6
- Profit Factor medio: ~1.44
- Sharpe medio: ~1.0
- MaxDD medio: ~8.7%

### Quando il bot resta flat
Il bot **non apre nessuna posizione** quando `daily_close ≤ SMA200 daily`.  
In regime flat/bear il log riporterà:
```
BTC_4H_BREAKOUT_DAILY_REGIME | strategy inactive by regime | daily_close=... SMA200=...
```
Questo è il comportamento corretto. Il mercato attuale (maggio 2026) è flat/bear:  
il bot deve restare flat finché il filtro non torna bullish.

---

## Struttura file

```
paper_trading_executor.py     # engine principale (state, risk, trade lifecycle)
live_runner_btc4h.py          # runner live per BTC_4H_BREAKOUT_DAILY_REGIME
strategies/
  __init__.py
  btc_4h_breakout_daily_regime.py   # logica strategia
tests/
  test_btc4h_strategy.py            # test di verifica locale
output/
  paper_trading_state.json          # stato persistente
  paper_trading_trades.csv          # storico trade
  paper_trading_log.jsonl           # log eventi
  paper_trading_runtime.json        # snapshot runtime
```

---

## Avvio

```bash
# Installa dipendenze
pip install -r requirements.txt

# Crea il file di configurazione
cp .env.example .env

# Esegui i test di verifica prima del deploy
python tests/test_btc4h_strategy.py

# Avvia il runner live
python live_runner_btc4h.py
```

---

## Risk management globale (invariato)

| Parametro | Valore |
|-----------|--------|
| Max drawdown stop | 7% |
| Daily loss stop | 2% |
| Max posizioni aperte | 3 |
| Cooldown re-entry | 30 min |
| Global risk cooldown | 6 ore |

---

## Criteri di monitoraggio (primi 3 mesi live)

1. **Profit Factor** — target ≥ 1.30 su almeno 20 trade chiusi
2. **Sharpe rolling 30gg** — target ≥ 0.8; sotto 0.5 per 2 settimane → review
3. **Max Drawdown** — alert a 5%; stop automatico a 7% (già configurato)
4. **Regime filter accuracy** — verifica settimanale che il bot sia flat  
   nei giorni in cui `daily_close < SMA200`
5. **Slippage reale vs atteso** — confronto mensile tra 0.10% stimato  
   e slippage effettivo registrato nei trade

---

## Strategie archiviate (non attive)

Le seguenti strategie sono state testate e scartate o risultate inferiori.  
Non modificare questi file.

- SMA crossover
- Mean reversion
- Breakout puro (senza filtro regime)

---

## Note operative

- Il log **non espone mai token o chiavi API**
- Lo stato del bot sopravvive ai riavvii tramite `output/paper_trading_state.json`
- In caso di anomalia usare `bot.resume_trading()` per sbloccare manualmente
- Non aggiungere nuovi parametri o indicatori senza un nuovo ciclo di walk-forward
