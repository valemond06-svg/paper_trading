# Daily Review Template — BTC_4H_BREAKOUT_DAILY_REGIME

> **Uso**: Compilare dopo ogni run di `live_runner_btc4h.py` e/o dopo un ciclo di trading live.
> Archiviare in `docs/reports/daily_YYYY-MM-DD.md`.
> Coerente con `docs/runbook.md` v1.0 e `docs/risk_events.md`.

---

## Meta

| Campo            | Valore                        |
|------------------|-------------------------------|
| **Data**         | YYYY-MM-DD                    |
| **Ora UTC**      | HH:MM UTC                     |
| **Run SHA**      | `<git rev-parse HEAD>`        |
| **Revisore**     | —                             |

---

## 1. Stato Strategia

| Campo               | Valore              |
|---------------------|---------------------|
| **Strategia attiva**| BTC_4H_BREAKOUT_DAILY_REGIME |
| **Regime corrente** | TREND / FLAT        |
| **Posizione aperta**| SÌ / NO             |
| **Side**            | LONG / SHORT / —    |
| **Entry price**     | $ —                 |
| **Stop attivo**     | $ —                 |

---

## 2. Stato Risk Engine

| Parametro               | Valore      | Note                  |
|-------------------------|-------------|-----------------------|
| **Bot paused**          | SÌ / NO     |                       |
| **daily_loss_stop hit** | SÌ / NO     | Soglia: 3%            |
| **Drawdown corrente**   | — %         | Da peak               |
| **Drawdown mensile**    | — %         |                       |
| **Loss consecutive**    | —           |                       |
| **Profit Factor (4w)**  | —           |                       |
| **Slippage medio**      | — %         |                       |
| **Regime FLAT consec.** | — giorni    |                       |

---

## 3. Stato Telegram

> Dedotto da log/output. Se non verificabile, indicare "N/V".

- Notifiche ricevute oggi: SÌ / NO / N/V
- Ultimo messaggio ricevuto: `HH:MM UTC — <testo>`
- Errori di delivery: SÌ / NO

---

## 4. Metriche Runtime

```
Equity corrente   : $ ___________
Cash disponibile  : $ ___________
Peak equity       : $ ___________
DD da peak        : ___ %
Trade totali      : ___
Trade chiusi oggi : ___
Win rate (totale) : ___ %
Last update state : YYYY-MM-DD HH:MM UTC
```

> Fonte: `output/state.json` — verificare con:
> ```bash
> python -c "import json; s=json.load(open('output/state.json')); \
> print('Equity:', s.get('equity'), '\nDD:', s.get('max_drawdown'), \
> '\nTrades:', s.get('trade_count'), '\nLast:', s.get('last_update'))"
> ```

---

## 5. Deviazioni rispetto al Baseline

> Compilare solo le righe pertinenti. Le soglie sono quelle del runbook § 9.

### 5.1 Drawdown

| Condizione                         | Stato oggi | Azione operativa richiesta                                              |
|------------------------------------|------------|-------------------------------------------------------------------------|
| DD corrente ≤ 5%                   | ✅ / ❌    | Nessuna                                                                 |
| DD corrente > 5% (**Soglia Attenzione**) | ✅ / ❌ | Aumentare monitoring; valutare apertura risk event `DD` se persiste     |
| DD corrente > 10% (**Soglia STOP bot**) | ✅ / ❌ | **STOP bot** → Documenta in `docs/risk_events.md` cat. AE/RB → No restart senza review |
| DD mensile > 8%                    | ✅ / ❌    | Soglia Attenzione mensile — revisione settimanale                       |
| DD mensile > 15%                   | ✅ / ❌    | Soglia STOP mensile — consulta `docs/decision_day90.md`                 |

### 5.2 Loss Consecutive

| Condizione                    | Stato oggi | Azione operativa richiesta                                    |
|-------------------------------|------------|---------------------------------------------------------------|
| Loss consecutive < 4          | ✅ / ❌    | Nessuna                                                       |
| Loss consecutive ≥ 4 (**Soglia Attenzione**) | ✅ / ❌ | Documenta + aumenta monitoring (L2 runbook)        |
| Loss consecutive ≥ 6 (**Soglia STOP bot**)   | ✅ / ❌ | STOP bot + risk event `RB` + review obbligatoria   |

### 5.3 Altre deviazioni

- [ ] Profit Factor (4w) < 1.2 → Soglia Attenzione
- [ ] Profit Factor (4w) < 0.9 → STOP bot
- [ ] Slippage medio > 0.15% → Soglia Attenzione (`SC`)
- [ ] Slippage medio > 0.30% → STOP bot (`SC`)
- [ ] Regime FLAT > 10 giorni consecutivi → Soglia Attenzione (`FZ`)
- [ ] Regime FLAT > 20 giorni consecutivi → STOP bot (`FZ`)
- [ ] Errori critici in log (ERROR / CRITICAL / Exception) → Verifica + eventuale `AE`

**Anomalie libere** (testo libero — se nessuna, scrivere "Nessuna"):
> —

---

## 6. Decisione Operativa

> Scegliere una sola opzione e motivare in una riga.

- [ ] **CONTINUE** — Nessuna deviazione. Bot opera normalmente.
- [ ] **MONITOR** — Soglia Attenzione raggiunta (specificare quale). Monitoraggio rafforzato.
- [ ] **PAUSE** — Attivare `_activate_pause` per sessione. Motivazione: ___
- [ ] **INVESTIGATE** — Comportamento anomalo rilevato. Analisi log in corso.
- [ ] **STOP** — Breach soglia STOP. Bot stoppato. Risk event aperto.

**Motivazione**:
> —

**Risk event aperto?** SÌ (`docs/risk_events.md`) / NO

---

## 7. Note Discrezionali

> Osservazioni di mercato, contesto macro, note non strutturate.

—

---

*Template generato il 2026-05-18 — coerente con `docs/runbook.md` v1.0*
