# Risk Events Log — BTC_4H_BREAKOUT_DAILY_REGIME

> Log di tutti gli eventi di rischio rilevati durante il live trading.
> Aggiornare non appena l'evento viene identificato.

---

## Categorie di Evento

| Codice | Descrizione |
|---|---|
| **DD** | Drawdown — superamento soglia DD giornaliero o settimanale |
| **SL** | Stop Loss Hit — stop triggerato, annotare condizioni |
| **RE** | Regime Error — regime classificato erroneamente o cambio rapido |
| **FZ** | Flat Zone — mercato FLAT prolungato > N giorni consecutivi |
| **RS** | Regime Switch — cambio di regime durante trade aperto |
| **RB** | Risk Breach — breach di un guardrail di rischio operativo |
| **AE** | Anomaly Event — comportamento anomalo del bot o dell'executor |
| **CC** | Connectivity/API — errore connessione exchange o API timeout |
| **MA** | Market Anomaly — spike, flash crash, liquidazioni di massa |
| **SC** | Slippage Critical — slippage > soglia operativa |

---

## Log degli Eventi

### Template per ogni entry

```markdown
### [CODICE] YYYY-MM-DD HH:MM UTC — Titolo breve evento

**Categoria**: DD / SL / RE / FZ / RS / RB / AE / CC / MA / SC
**Severity**: LOW / MEDIUM / HIGH / CRITICAL
**Stato**: OPEN / RESOLVED / MONITORING

**Descrizione**:
[Cosa è successo esattamente]

**Dati al momento dell'evento**:
- Equity: $
- Drawdown corrente: %
- Regime: TREND / FLAT
- Posizione aperta: SÌ / NO

**Azione intrapresa**:
[Cosa è stato fatto: restart, stop, nessuna azione, etc.]

**Risoluzione**:
[Come e quando è stato risolto]

**Follow-up necessario**:
- [ ] Azione 1
- [ ] Azione 2
```

---

## Storico Eventi

> *Nessun evento registrato. Il log inizierà con il go-live.*

---

## Summary Counters

| Categoria | Count | Ultimo Evento |
|---|---|---|
| DD | 0 | — |
| SL | 0 | — |
| RE | 0 | — |
| FZ | 0 | — |
| RS | 0 | — |
| RB | 0 | — |
| AE | 0 | — |
| CC | 0 | — |
| MA | 0 | — |
| SC | 0 | — |
