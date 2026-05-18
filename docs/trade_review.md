# Trade Review — Template

> Compilare per ogni trade chiuso. Un file per settimana o per trade, a discrezione.
> Archiviare in `docs/reports/` con naming `trade_YYYY-MM-DD_HHmm.md`.

---

## Identificativo Trade

| Campo | Valore |
|---|---|
| **Trade ID** | `#NNN` |
| **Timestamp apertura** | `YYYY-MM-DD HH:MM UTC` |
| **Timestamp chiusura** | `YYYY-MM-DD HH:MM UTC` |
| **Durata** | `Xh Ym` |

---

## Condizioni di Mercato

| Campo | Valore |
|---|---|
| **Regime giornaliero** | `TREND` / `FLAT` |
| **Segnale 4H** | `LONG_BREAKOUT` / `SHORT_BREAKOUT` / `NO_SIGNAL` |
| **ADX al segnale** | ` ` |
| **DI+ / DI-** | ` / ` |
| **Volume relativo** | `Alto` / `Medio` / `Basso` |

---

## Esecuzione

| Campo | Valore |
|---|---|
| **Direzione** | `LONG` / `SHORT` |
| **Prezzo Entry** | `$` |
| **Prezzo Exit** | `$` |
| **Stop Loss** | `$` (` %`) |
| **Target** | `$` (` %`) |
| **Size (BTC)** | ` ` |
| **Size (USDT notional)** | `$` |
| **% del capitale** | ` %` |

---

## Risultato

| Campo | Valore |
|---|---|
| **PnL (USDT)** | `+/- $` |
| **PnL (%)** | `+/- %` |
| **Slippage entry** | ` %` |
| **Slippage exit** | ` %` |
| **Slippage totale** | ` %` |
| **Uscita per** | `Target` / `Stop` / `Regime change` / `Manuale` |

---

## Valutazione Qualitativa

**Il setup era valido rispetto alle regole della strategia?**
- [ ] Sì, segnale conforme
- [ ] Parzialmente conforme (descrivere sotto)
- [ ] Non conforme — anomalia

**Esecuzione corretta?**
- [ ] Sì
- [ ] No — descrivere deviazione

**Lezioni apprese / Note**:

```
[Inserire osservazioni libere: comportamento del prezzo, slippage inatteso,
 regime ambiguo, condizioni macro, etc.]
```

---

## Equity Post-Trade

| Campo | Valore |
|---|---|
| **Equity prima** | `$` |
| **Equity dopo** | `$` |
| **Drawdown corrente** | ` %` |
| **Consecutive losses** | ` ` |
