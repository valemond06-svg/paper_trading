# Decision Day-90 — Template Valutazione Go/Extend/No-Go

> Da compilare al **giorno 90 di live trading** (o prima se viene attivata l'escalation).
> Questo documento determina il destino operativo della strategia BTC_4H_BREAKOUT_DAILY_REGIME.

---

## Intestazione

| Campo | Valore |
|---|---|
| **Data valutazione** | `YYYY-MM-DD` |
| **Periodo valutato** | `YYYY-MM-DD → YYYY-MM-DD` |
| **Giorni effettivi di live** | ` ` |
| **Compilato da** | ` ` |

---

## 1. Metriche Oggettive

### 1.1 Performance

| Metrica | Backtest Target | Soglia Minima | Live Actual | Status |
|---|---|---|---|---|
| **Profit Factor (90gg)** | ≥ 1.5 | ≥ 1.1 | ` ` | ✅/⚠️/🛑 |
| **Win Rate (%)** | ≥ 45% | ≥ 38% | ` %` | ✅/⚠️/🛑 |
| **Avg Trade Return (%)** | ≥ 0.8% | ≥ 0.3% | ` %` | ✅/⚠️/🛑 |
| **Total PnL (%)** | ≥ +10% | ≥ 0% | ` %` | ✅/⚠️/🛑 |
| **Trade count** | ≥ 20 | ≥ 10 | ` ` | ✅/⚠️/🛑 |

### 1.2 Rischio

| Metrica | Soglia OK | Soglia NO-GO | Live Actual | Status |
|---|---|---|---|---|
| **MaxDD (%)** | < 10% | > 20% | ` %` | ✅/⚠️/🛑 |
| **MaxDD / Backtest MaxDD** | < 1.5x | > 2.5x | ` x` | ✅/⚠️/🛑 |
| **Max consecutive losses** | ≤ 5 | > 8 | ` ` | ✅/⚠️/🛑 |
| **Avg slippage (%)** | < 0.15% | > 0.30% | ` %` | ✅/⚠️/🛑 |
| **Risk events HIGH/CRITICAL** | 0 | ≥ 2 | ` ` | ✅/⚠️/🛑 |

### 1.3 Regime

| Metrica | Valore |
|---|---|
| **% giorni TREND** | ` %` |
| **% giorni FLAT** | ` %` |
| **Trade in FLAT** | 0 (se > 0: bug critico) |
| **Coerenza classificazione regime** | Alta / Media / Bassa |

---

## 2. Score Card

> Assegna 1 punto per ogni soglia superata (✅), 0 per ⚠️, -1 per 🛑.

| Area | Peso | Score raw | Score pesato |
|---|---|---|---|
| Performance | 40% | ` /5` | ` ` |
| Rischio | 40% | ` /5` | ` ` |
| Regime | 20% | ` /3` | ` ` |
| **TOTALE** | 100% | — | ` /10` |

---

## 3. Esito — Soglie Oggettive

| Score | Esito | Significato |
|---|---|---|
| ≥ 7.0 | **GO** | Prosegui live, aumenta sizing gradualmente |
| 4.0 – 6.9 | **EXTEND** | Altri 30-60 giorni paper con review |
| < 4.0 | **NO-GO** | Sospendi live, ritorna a backtest/ottimizzazione |

> ⚠️ **Override automatico NO-GO** (indipendente dallo score):
> - MaxDD live > 20%
> - ≥ 2 eventi CRITICAL in `docs/risk_events.md`
> - Trade aperti in regime FLAT
> - PF < 0.9 nelle ultime 4 settimane

---

## 4. Esito Finale

**Decisione**:
- [ ] ✅ **GO** — il sistema è approvato per sizing reale
- [ ] ⏳ **EXTEND** — prolungamento paper di _____ giorni
- [ ] 🛑 **NO-GO** — sospensione e ritorno a ricerca

**Score finale**: ` /10`

**Motivazione**:
```
[Sintesi della valutazione. Punti forti, punti deboli, rischi residui,
condizioni di mercato durante il periodo, divergenze dal backtest.]
```

**Prossimi passi**:
```
[Se GO: piano scaling sizing, revisione rischio, timeline.
 Se EXTEND: nuove metriche target, data prossima review.
 Se NO-GO: ipotesi di fallimento, cosa riformulare nel backtest.]
```

**Firma**: _________________________ Data: _____________
