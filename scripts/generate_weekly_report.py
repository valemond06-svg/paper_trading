#!/usr/bin/env python3
"""
generate_weekly_report.py

Wrapper minimale per report settimanale BTC_4H_BREAKOUT_DAILY_REGIME.
Legge solo:
  - output/paper_trading_state.json
  - output/paper_trading_runtime.json

Genera:
  - docs/reports/week_YYYY_WW.md

Non modifica alcun file del motore live.
Non importa moduli del bot.

Usage:
  python scripts/generate_weekly_report.py
  python scripts/generate_weekly_report.py --week 2026-W20
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — tutti relativi alla root del repo
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "output" / "paper_trading_state.json"
REPORT_FILE = REPO_ROOT / "output" / "paper_trading_runtime.json"
OUTPUT_DIR = REPO_ROOT / "docs" / "reports"


def fail(msg: str) -> None:
    """Termina con errore leggibile."""
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> dict:
    """Carica un file JSON con messaggio di errore chiaro se mancante."""
    if not path.exists():
        fail(
            f"File non trovato: {path}\n"
            f"       Assicurati che il bot abbia girato almeno una volta "
            f"e che il file sia stato generato."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        fail(f"JSON non valido in {path}: {e}")


def parse_week_arg(week_str: str) -> tuple[int, int]:
    """
    Parsa --week YYYY-WNN e restituisce (year, week_number).
    Formato atteso: 2026-W20 oppure 2026-20
    """
    week_str = week_str.strip().upper().replace("-W", "-")
    parts = week_str.split("-")
    if len(parts) != 2:
        fail(f"Formato --week non valido: '{week_str}'. Usa YYYY-WNN (es. 2026-W20)")
    try:
        year = int(parts[0])
        week = int(parts[1])
    except ValueError:
        fail(f"Formato --week non valido: '{week_str}'. Usa YYYY-WNN (es. 2026-W20)")
    if not (1 <= week <= 53):
        fail(f"Numero settimana non valido: {week}")
    return year, week


def current_iso_week() -> tuple[int, int]:
    """Restituisce (year, week) della settimana ISO corrente."""
    today = datetime.now(tz=timezone.utc)
    iso = today.isocalendar()
    return iso.year, iso.week


def week_date_range(year: int, week: int) -> tuple[str, str]:
    """Restituisce (start_date, end_date) della settimana ISO come stringhe YYYY-MM-DD."""
    # ISO week 1 day 1 = lunedì
    jan4 = datetime(year, 1, 4)
    start = jan4 + timedelta(weeks=week - 1, days=-jan4.weekday())
    end = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def extract_weekly_trades(report_data: dict, year: int, week: int) -> list[dict]:
    """
    Filtra i trade del report per la settimana specificata.
    Gestisce sia lista di trade top-level che sotto chiave 'trades'.
    """
    trades_raw = report_data if isinstance(report_data, list) else report_data.get("trades", [])
    if not isinstance(trades_raw, list):
        return []

    start_str, end_str = week_date_range(year, week)
    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str) + timedelta(hours=23, minutes=59, seconds=59)

    weekly = []
    for t in trades_raw:
        # Cerca timestamp in campi comuni
        ts_raw = t.get("exit_time") or t.get("close_time") or t.get("timestamp") or t.get("time")
        if not ts_raw:
            continue
        try:
            # Normalizza: rimuovi Z, gestisci offset
            ts_str = str(ts_raw).replace("Z", "+00:00")
            ts_dt = datetime.fromisoformat(ts_str).replace(tzinfo=None)
            if start_dt <= ts_dt <= end_dt:
                weekly.append(t)
        except (ValueError, TypeError):
            continue
    return weekly


def compute_stats(trades: list[dict]) -> dict:
    """Calcola statistiche sui trade della settimana."""
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "gross_profit": 0.0,
            "gross_loss": 0.0, "profit_factor": None,
            "net_pnl": 0.0, "avg_pnl": 0.0,
        }

    pnls = []
    for t in trades:
        pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl") or 0.0
        try:
            pnls.append(float(pnl))
        except (TypeError, ValueError):
            pnls.append(0.0)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else None

    return {
        "count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(pf, 3) if pf is not None else "N/A (no losses)",
        "net_pnl": round(net_pnl, 2),
        "avg_pnl": round(net_pnl / len(pnls), 2) if pnls else 0.0,
    }


def format_trade_row(t: dict) -> str:
    """Formatta un trade come riga di tabella Markdown."""
    ts = t.get("exit_time") or t.get("close_time") or t.get("timestamp") or "—"
    direction = t.get("side") or t.get("direction") or t.get("type") or "—"
    entry = t.get("entry_price") or t.get("open_price") or "—"
    exit_ = t.get("exit_price") or t.get("close_price") or "—"
    pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl") or 0.0
    regime = t.get("regime") or t.get("daily_regime") or "—"
    try:
        pnl_fmt = f"{float(pnl):+.2f}"
    except (TypeError, ValueError):
        pnl_fmt = str(pnl)
    return f"| {ts} | {direction} | {regime} | {entry} | {exit_} | {pnl_fmt} |"


def generate_report(state: dict, report_data: dict, year: int, week: int) -> str:
    """Genera il contenuto del report settimanale in Markdown."""
    start_date, end_date = week_date_range(year, week)
    weekly_trades = extract_weekly_trades(report_data, year, week)
    stats = compute_stats(weekly_trades)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Dati da paper_trading_state.json
    equity = state.get("equity", "N/A")
    regime = state.get("daily_regime", "N/A")
    max_dd = state.get("max_drawdown", "N/A")
    last_update = state.get("last_update", state.get("updated_at", "N/A"))
    open_position = state.get("open_position", None) or state.get("positions", None)
    trade_count_total = state.get("trade_count", len(state.get("trade_history", state.get("tradehistory", []))))

    pf_val = stats["profit_factor"]
    pf_status = ""
    if isinstance(pf_val, (int, float)):
        if pf_val >= 1.5:
            pf_status = " ✅"
        elif pf_val >= 1.1:
            pf_status = " ⚠️"
        else:
            pf_status = " 🛑"

    lines = [
        f"# Weekly Report — Week {year}-W{week:02d}",
        f"",
        f"> **Periodo**: {start_date} → {end_date}  ",
        f"> **Generato**: {now}  ",
        f"> **Strategia**: BTC_4H_BREAKOUT_DAILY_REGIME  ",
        f">",
        f"---",
        f"",
        f"## 1. Snapshot Stato Bot",
        f"",
        f"| Parametro | Valore |",
        f"|---|---|",
        f"| Equity corrente | {equity} |",
        f"| Regime (al momento del report) | {regime} |",
        f"| Max Drawdown cumulato | {max_dd} |",
        f"| Posizione aperta | {'SÌ' if open_position else 'NO'} |",
        f"| Trade totali (dall'avvio) | {trade_count_total} |",
        f"| Ultimo aggiornamento state | {last_update} |",
        f"",
        f"---",
        f"",
        f"## 2. Performance Settimanale",
        f"",
        f"| Metrica | Valore |",
        f"|---|---|",
        f"| Trade settimana | {stats['count']} |",
        f"| Wins | {stats['wins']} |",
        f"| Losses | {stats['losses']} |",
        f"| Win Rate | {stats['win_rate']}% |",
        f"| Net PnL | {stats['net_pnl']:+.2f} USDT |",
        f"| Avg PnL per trade | {stats['avg_pnl']:+.2f} USDT |",
        f"| Gross Profit | {stats['gross_profit']:.2f} USDT |",
        f"| Gross Loss | {stats['gross_loss']:.2f} USDT |",
        f"| Profit Factor | {pf_val}{pf_status} |",
        f"",
        f"---",
        f"",
        f"## 3. Dettaglio Trade",
        f"",
    ]

    if weekly_trades:
        lines.append("| Timestamp Exit | Direzione | Regime | Entry | Exit | PnL (USDT) |")
        lines.append("|---|---|---|---|---|---|")
        for t in weekly_trades:
            lines.append(format_trade_row(t))
    else:
        lines.append("> *Nessun trade chiuso in questa settimana.*")
        lines.append(">")
        lines.append("> Possibili cause: regime FLAT per tutta la settimana, "
                     "nessun breakout valido, o bot non attivo.")

    lines += [
        f"",
        f"---",
        f"",
        f"## 4. Checklist Post-Report",
        f"",
        f"- [ ] PF > 1.2 (soglia attenzione)",
        f"- [ ] Net PnL > 0",
        f"- [ ] Nessun risk event HIGH/CRITICAL questa settimana",
        f"- [ ] Slippage medio nella norma (< 0.15%)",
        f"- [ ] `paper_trading_state.json` aggiornato correttamente",
        f"- [ ] Trade documentati in `docs/trade_review.md`",
        f"",
        f"---",
        f"",
        f"## 5. Note Operative",
        f"",
        f"```",
        f"[Inserire note manuali: anomalie, condizioni mercato, decisioni prese]",
        f"```",
        f"",
        f"---",
        f"*Report generato automaticamente da `scripts/generate_weekly_report.py`.*  ",
        f"*Non modificare i file del motore live. Solo lettura da output/.*",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera report settimanale da paper_trading_state.json e paper_trading_runtime.json"
    )
    parser.add_argument(
        "--week",
        type=str,
        default=None,
        help="Settimana ISO da reportare (es. 2026-W20). Default: settimana corrente.",
    )
    args = parser.parse_args()

    # Determina settimana
    if args.week:
        year, week = parse_week_arg(args.week)
    else:
        year, week = current_iso_week()

    print(f"[INFO] Generando report per settimana {year}-W{week:02d}")
    print(f"[INFO] Lettura da: {STATE_FILE}")
    print(f"[INFO] Lettura da: {REPORT_FILE}")

    # Carica file — fallisce in modo leggibile se mancanti
    state = load_json(STATE_FILE)
    report_data = load_json(REPORT_FILE)

    # Genera contenuto
    content = generate_report(state, report_data, year, week)

    # Crea output dir se non esiste
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Scrivi file
    output_file = OUTPUT_DIR / f"week_{year}_{week:02d}.md"
    output_file.write_text(content, encoding="utf-8")

    print(f"[OK] Report generato: {output_file.relative_to(REPO_ROOT)}")
    print(f"[OK] Aprilo con: cat {output_file.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
