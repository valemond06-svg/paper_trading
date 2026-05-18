# Runbook Operativo — BTC_4H_BREAKOUT_DAILY_REGIME

> **Versione**: 1.0 | **Strategia**: BTC_4H_BREAKOUT_DAILY_REGIME | **Aggiornato**: 2026-05-17

---

## 1. Avvio Bot

```bash
# 1. Attiva virtualenv
source .venv/bin/activate

# 2. Verifica variabili d'ambiente
cat .env | grep -E 'EXCHANGE|API_KEY|PAPER'

# 3. Avvia il live runner
python live_runner_btc4h.py

# Oppure in background con nohup
nohup python live_runner_btc4h.py > logs/bot.log 2>&1 &
echo $! > bot.pid
```

**Output atteso all'avvio**:
- `[INFO] Regime: TREND | FLAT` (dipende dalle condizioni di mercato)
- `[INFO] State loaded from output/state.json`
- `[INFO] Scheduler started. Next candle check: HH:MM`

---

## 2. Stop / Restart

```bash
# Stop pulito
kill $(cat bot.pid)

# Verifica che il processo sia terminato
ps aux | grep live_runner_btc4h

# Restart
nohup python live_runner_btc4h.py > logs/bot.log 2>&1 &
echo $! > bot.pid
```

> ⚠️ **Non interrompere durante la chiusura di un trade aperto.** Verificare `state.json` prima di stoppare.

---

## 3. Verifica Regime FLAT

Il bot non opera quando il regime giornaliero è FLAT. Per verificare:

```bash
# Controlla regime attuale
python -c "import json; s=json.load(open('output/state.json')); print('Regime:', s.get('daily_regime', 'N/A'))"

# Output atteso: Regime: FLAT  oppure  Regime: TREND
```

**Se FLAT**: nessun nuovo segnale verrà aperto. Posizioni aperte precedenti restano gestite dallo stop.

---

## 4. Controllo Log

```bash
# Ultime 50 righe
tail -n 50 logs/bot.log

# Ricerca errori
grep -E 'ERROR|CRITICAL|Exception' logs/bot.log | tail -20

# Log in tempo reale
tail -f logs/bot.log

# Filtra per trade events
grep -E 'SIGNAL|ENTRY|EXIT|STOP|TARGET' logs/bot.log | tail -30
```

---

## 5. Controllo state.json

```bash
# Visualizza stato completo
python -c "import json; print(json.dumps(json.load(open('output/state.json')), indent=2))"

# Chiavi critiche da verificare
python -c "
import json
s = json.load(open('output/state.json'))
print('Equity:', s.get('equity'))
print('Open position:', s.get('open_position'))
print('Regime:', s.get('daily_regime'))
print('Last update:', s.get('last_update'))
print('Trade count:', s.get('trade_count'))
print('Max DD:', s.get('max_drawdown'))
"
```

---

## 6. Checklist Giornaliera

Eseguire ogni giorno entro le **09:00 CET**:

- [ ] Bot in esecuzione (`ps aux | grep live_runner`)
- [ ] Nessun errore critico nei log delle ultime 24h
- [ ] Regime aggiornato correttamente (coerente con mercato)
- [ ] Equity > soglia minima (vedi § Guardrail)
- [ ] Posizione aperta documentata in `docs/trade_review.md` se presente
- [ ] `state.json` aggiornato con timestamp recente (< 5h)
- [ ] Nessun risk event da registrare in `docs/risk_events.md`

---

## 7. Checklist Settimanale

Eseguire ogni **lunedì mattina**:

- [ ] Generare report settimanale: `python scripts/generate_weekly_report.py`
- [ ] Leggere il report in `docs/reports/week_YYYY_WW.md`
- [ ] Verificare PF settimanale > 1.0 (soglia attenzione)
- [ ] Verificare Max DD settimanale < 8%
- [ ] Compilare `docs/trade_review.md` per ogni trade chiuso della settimana
- [ ] Registrare eventuali anomalie in `docs/risk_events.md`
- [ ] Aggiornare equity curve (grafico opzionale)

---

## 8. Checklist Mensile

- [ ] Compilare `docs/monthly_review.md`
- [ ] Confronto PF effettivo vs backtest
- [ ] Confronto Max DD effettivo vs backtest
- [ ] Analisi distribuzione regime (TREND vs FLAT)
- [ ] Revisione slippage medio
- [ ] Decisione: continuare, aggiustare parametri o escalate a Day-90

---

## 9. Guardrail di Rischio

| Parametro | Soglia Attenzione | Soglia STOP bot |
|---|---|---|
| Drawdown corrente | > 5% | > 10% |
| Drawdown su mese | > 8% | > 15% |
| Perdite consecutive | ≥ 4 | ≥ 6 |
| Profit Factor (4 settimane) | < 1.2 | < 0.9 |
| Slippage medio per trade | > 0.15% | > 0.30% |
| Regime FLAT consecutivi | > 10 giorni | > 20 giorni |

**In caso di breach della soglia STOP**:
1. Stop bot (`kill $(cat bot.pid)`)
2. Documenta evento in `docs/risk_events.md` con categoria AE
3. Non riavviare senza review documentata
4. Consulta `docs/decision_day90.md` per escalation

---

## 10. Contatti e Escalation

| Livello | Azione |
|---|---|
| L1 – Anomalia log | Verifica + restart se necessario |
| L2 – Breach soglia attenzione | Documenta + aumenta monitoring |
| L3 – Breach soglia STOP | Stop bot + review obbligatoria |
| L4 – Perdita > 15% equity | NO-GO: sospendi live, avvia analisi |
