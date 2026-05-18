# Monthly Review — Template

> Compilare entro il **5 del mese successivo**.
> Naming: `docs/reports/monthly_YYYY_MM.md`

---

## Intestazione

| Campo | Valore |
|---|---|
| **Mese** | `YYYY-MM` |
| **Strategia** | BTC_4H_BREAKOUT_DAILY_REGIME |
| **Compilato da** | ` ` |
| **Data compilazione** | `YYYY-MM-DD` |

---

## 1. Equity Summary

| Metrica | Valore |
|---|---|
| **Equity inizio mese** | `$` |
| **Equity fine mese** | `$` |
| **PnL mese (USDT)** | `+/- $` |
| **PnL mese (%)** | `+/- %` |
| **PnL cumulato dall'avvio** | `+/- %` |
| **Equity peak del mese** | `$` |
| **Equity trough del mese** | `$` |

---

## 2. Profit Factor (PF)

| Metrica | Valore |
|---|---|
| **Gross profit (USDT)** | `$` |
| **Gross loss (USDT)** | `$` |
| **Profit Factor** | ` ` |
| **PF soglia attenzione** | 1.2 |
| **PF soglia STOP** | 0.9 |
| **Status** | ✅ OK / ⚠️ Attenzione / 🛑 STOP |

---

## 3. Max Drawdown (MaxDD)

| Metrica | Valore |
|---|---|
| **MaxDD del mese (%)** | ` %` |
| **MaxDD cumulato (%)** | ` %` |
| **Data MaxDD** | `YYYY-MM-DD` |
| **Soglia attenzione** | 8% |
| **Soglia STOP** | 15% |
| **Status** | ✅ OK / ⚠️ Attenzione / 🛑 STOP |

---

## 4. Trade Count & Statistics

| Metrica | Valore |
|---|---|
| **Totale trade** | ` ` |
| **Win** | ` ` |
| **Loss** | ` ` |
| **Win rate (%)** | ` %` |
| **Avg win (USDT)** | `$` |
| **Avg loss (USDT)** | `$` |
| **Avg W/L ratio** | ` ` |
| **Max consecutive losses** | ` ` |
| **Avg slippage per trade (%)** | ` %` |

---

## 5. Distribuzione Regime

| Regime | Giorni | % mese | Trade aperti |
|---|---|---|---|
| TREND | ` ` | ` %` | ` ` |
| FLAT | ` ` | ` %` | 0 (corretto) |

**Note sul regime**:
```
[Osservazioni: periodi anomali, cambi rapidi, false classificazioni sospette]
```

---

## 6. Confronto con Backtest

| Metrica | Backtest | Live mese | Delta |
|---|---|---|---|
| Win rate | `%` | `%` | `+/- pp` |
| Profit Factor | ` ` | ` ` | `+/-` |
| Avg trade (%) | `%` | `%` | `+/- pp` |
| Max DD mensile | `%` | `%` | `+/- pp` |
| Trade/mese | ` ` | ` ` | `+/-` |

**Valutazione divergenza**:
- [ ] Divergenza entro aspettative statistiche
- [ ] Divergenza moderata — monitorare
- [ ] Divergenza significativa — review strategia

```
[Commento libero: cause della divergenza, condizioni di mercato, overfitting sospetto, etc.]
```

---

## 7. Risk Events del Mese

| Data | Categoria | Severity | Risolto |
|---|---|---|---|
| — | — | — | — |

*(Dettagli in `docs/risk_events.md`)*

---

## 8. Decisioni

**Decisione operativa per il mese successivo**:
- [ ] **CONTINUA** — parametri invariati
- [ ] **AGGIUSTA** — specificare parametro e modifica:
  ```
  Parametro: 
  Valore attuale: 
  Valore nuovo: 
  Motivazione: 
  ```
- [ ] **ESCALATE** — avvia procedura `docs/decision_day90.md`
- [ ] **STOP** — sospendi live, analisi post-mortem

**Note aggiuntive**:
```
[Osservazioni finali, contesto macro, piani per il mese successivo]
```
