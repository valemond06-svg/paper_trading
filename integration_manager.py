import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
from dotenv import load_dotenv

from price_feed_adapter import PriceFeedAdapter
from paper_trading_executor import PaperTradingBot
from utils.logging_utils import json_log, redact

load_dotenv()

OUT = Path("output")
OUT.mkdir(exist_ok=True)

MANAGER_STATE = OUT / "integration_manager_state.json"
MANAGER_LOG = OUT / "integration_manager_log.jsonl"
FEED_STATE_JSON = OUT / "price_feed_state.json"
INTEGRATION_BUNDLE = OUT / "integration_bundle.json"
PAPER_TRADING_LOG = OUT / "paper_trading_log.txt"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAMBOTTOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAMCHATID")
# TELEGRAM_ALLOWED_CHAT_ID: chat ID autorizzato per comandi critici.
# Default: TELEGRAM_CHAT_ID per retrocompatibilità.
TELEGRAM_ALLOWED_CHAT_ID = (
    os.getenv("TELEGRAM_ALLOWED_CHAT_ID")
    or TELEGRAM_CHAT_ID
)

DEFAULT_POLL_SECONDS = 5
TELEGRAM_TIMEOUT = (10, 25)
TELEGRAM_LONG_POLL_TIMEOUT = 20
TELEGRAM_POLL_SLEEP = 1.0
# Reduced from 270s to 210s to avoid overlap with the external 5-min cron trigger.
RUN_BUDGET_SECONDS = 210
RUN_SLEEP_SECONDS = DEFAULT_POLL_SECONDS
SAFETY_MARGIN_SECONDS = 15
LOG_TAIL_LINES = 20


class IntegrationManager:
    def __init__(self) -> None:
        self.feed = PriceFeedAdapter()
        self.executor = PaperTradingBot()
        self.executor.load_state()

        self.paused = False
        self.last_prices: Dict[str, float] = {}

        self.telegram_enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        self.telegram_offset: Optional[int] = None

        self.notified_trade_ids: Set[str] = set()
        self.notified_open_symbols: Set[str] = set()
        self.notifications_bootstrapped = False

        self.last_summary_text: str = ""
        self.last_manager_pause_state: Optional[bool] = None

        self.http = requests.Session()

        self.load_state()
        self._bootstrap_notification_state()
        self.log("Integration manager initialized")

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _atomic_write_text(self, path: Path, text: str) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)

    def log(self, message: str, level: str = "INFO", **data) -> None:
        safe = redact(str(message))
        json_log(MANAGER_LOG, event=safe, component="integration_manager",
                 level=level, **data)
        print(f"{self._now_iso()} | {safe}")

    def load_state(self) -> None:
        if not MANAGER_STATE.exists():
            return

        state = json.loads(MANAGER_STATE.read_text(encoding="utf-8"))
        self.paused = bool(state.get("paused", False))
        self.last_prices = state.get("last_prices", {}) or state.get("lastprices", {}) or {}
        self.notified_trade_ids = set(state.get("notified_trade_ids", []))
        self.notified_open_symbols = set(state.get("notified_open_symbols", []))
        self.telegram_offset = state.get("telegram_offset")
        self.notifications_bootstrapped = bool(state.get("notifications_bootstrapped", False))
        self.last_summary_text = str(state.get("last_summary_text", "") or "")

    def save_state(self) -> None:
        state = {
            "paused": self.paused,
            "last_prices": self.last_prices,
            "notified_trade_ids": sorted(self.notified_trade_ids),
            "notified_open_symbols": sorted(self.notified_open_symbols),
            "telegram_offset": self.telegram_offset,
            "notifications_bootstrapped": self.notifications_bootstrapped,
            "last_summary_text": self.last_summary_text,
            "updated_at": self._now_iso(),
        }
        self._atomic_write_text(MANAGER_STATE, json.dumps(state, indent=2))

    def _bootstrap_notification_state(self) -> None:
        if self.notifications_bootstrapped:
            return

        self.notified_open_symbols = set(self.executor.positions.keys())

        for trade in self.executor.trade_history:
            trade_id = getattr(trade, "trade_id", None)
            if trade_id:
                self.notified_trade_ids.add(trade_id)

        self.notifications_bootstrapped = True
        self.save_state()

    def telegram_api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

    def send_telegram_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        if not self.telegram_enabled:
            return False

        target = chat_id or TELEGRAM_CHAT_ID
        payload = {
            "chat_id": target,
            "text": text[:4000],
            "parse_mode": "HTML",
        }

        try:
            resp = self.http.post(
                self.telegram_api_url("sendMessage"),
                data=payload,
                timeout=TELEGRAM_TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            self.log(f"Telegram send failed: {e}")
            return False

    def get_telegram_updates(self) -> List[dict]:
        if not self.telegram_enabled:
            return []

        payload = {
            "timeout": TELEGRAM_LONG_POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message"]),
        }
        if self.telegram_offset is not None:
            payload["offset"] = self.telegram_offset

        try:
            resp = self.http.get(
                self.telegram_api_url("getUpdates"),
                params=payload,
                timeout=(10, TELEGRAM_LONG_POLL_TIMEOUT + 5),
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                self.log(f"Telegram getUpdates not ok: {data}")
                return []
            return data.get("result", [])
        except Exception as e:
            self.log(f"Telegram getUpdates failed: {e}")
            return []

    def sync_prices_to_executor(self, prices: Dict[str, float]) -> None:
        self.last_prices = prices
        self.executor.ingest_prices(prices)
        self.executor.save_state()
        self.save_state()

    def maybe_trade(self) -> None:
        if self.paused:
            if self.last_manager_pause_state is not True:
                self.log("Manager paused")
                self.last_manager_pause_state = True
            return

        self.last_manager_pause_state = False
        self.executor.maybe_rebalance()
        self.executor.export_runtime_report()
        self.executor.save_state()
        self.save_state()

    def _format_open_message(self, symbol: str) -> str:
        pos = self.executor.positions[symbol]
        return (
            "OPEN POSITION\n"
            f"Symbol: {pos.symbol}\n"
            f"Asset: {pos.asset}\n"
            f"Timeframe: {pos.timeframe}\n"
            f"Strategy: {pos.strategy}\n"
            f"Side: {pos.side}\n"
            f"Qty: {pos.quantity:.6f}\n"
            f"Entry: {pos.entry_price:.4f}\n"
            f"Stop: {pos.stop_price:.4f}\n"
            f"Take profit: {pos.take_profit:.4f}\n"
            f"Target weight: {pos.target_weight:.4f}"
        )

    def _format_close_message(self, trade) -> str:
        status = self.executor.status()
        return (
            "CLOSE POSITION\n"
            f"Symbol: {trade.symbol}\n"
            f"Asset: {trade.asset}\n"
            f"Timeframe: {trade.timeframe}\n"
            f"Strategy: {trade.strategy}\n"
            f"Reason: {trade.reason}\n"
            f"Entry: {trade.entry_price:.4f}\n"
            f"Exit: {trade.exit_price:.4f}\n"
            f"Qty: {trade.quantity:.6f}\n"
            f"Gross PnL: {trade.gross_pnl:.4f}\n"
            f"Net PnL: {trade.net_pnl:.4f}\n"
            f"Fees: {trade.fees:.4f}\n"
            f"Equity: {status['equity']:.2f}"
        )

    def notify_new_opens_and_closes(self) -> None:
        if not self.telegram_enabled:
            return

        current_open_symbols = set(self.executor.positions.keys())

        new_opens = sorted(current_open_symbols - self.notified_open_symbols)
        for symbol in new_opens:
            if symbol in self.executor.positions:
                self.send_telegram_message(self._format_open_message(symbol))
                self.notified_open_symbols.add(symbol)
                self.save_state()

        removed_symbols = self.notified_open_symbols - current_open_symbols
        if removed_symbols:
            self.notified_open_symbols = current_open_symbols.copy()
            self.save_state()

        for trade in self.executor.trade_history:
            trade_id = getattr(trade, "trade_id", None)
            if not trade_id or trade_id in self.notified_trade_ids:
                continue
            self.send_telegram_message(self._format_close_message(trade))
            self.notified_trade_ids.add(trade_id)
            self.save_state()

    def status(self) -> dict:
        status = self.executor.status()
        status["manager_paused"] = self.paused
        status["last_price_symbols"] = sorted(list(self.last_prices.keys()))
        return status

    def summary_text(self) -> str:
        s = self.status()
        lines = [
            "INTEGRATION MANAGER STATUS",
            f"Equity: {s['equity']:.2f}",
            f"Cash: {s['cash']:.2f}",
            f"Drawdown: {s['drawdown'] * 100:.2f}%",
            f"Daily loss: {s['dailyloss'] * 100:.2f}%",
            f"Open positions: {s['openpositions']}",
            f"Paused: {s['paused'] or s['manager_paused']}",
            f"Pause reason: {s.get('pausereason', s.get('pause_reason', '')) or 'none'}",
            f"Paused until: {s.get('pauseduntil', s.get('paused_until', '')) or 'none'}",
            f"Consecutive losses: {s['consecutivelosses']}",
            f"Last price symbols: {', '.join(s['last_price_symbols']) if s['last_price_symbols'] else 'none'}",
        ]
        return "\n".join(lines)

    def render_positions(self) -> str:
        if not self.executor.positions:
            return "No open positions."

        lines = []
        for p in self.executor.positions.values():
            lines.append(
                f"{p.asset} {p.timeframe} {p.strategy} "
                f"qty={p.quantity:.6f} entry={p.entry_price:.4f} "
                f"stop={p.stop_price:.4f} tp={p.take_profit:.4f}"
            )
        return "\n".join(lines)

    def render_trades(self, limit: int = 10) -> str:
        trades = self.executor.trade_history[-limit:]
        if not trades:
            return "No closed trades."

        lines = []
        for t in trades:
            lines.append(
                f"{t.asset} {t.timeframe} {t.strategy} "
                f"side={t.side} net={t.net_pnl:.4f} fees={t.fees:.4f} "
                f"reason={t.reason} at {t.timestamp}"
            )
        return "\n".join(lines)

    def render_report(self) -> str:
        bundle = self.export_bundle()
        manager = bundle.get("manager", {})
        executor = bundle.get("executor", {})

        lines = [
            "\U0001f4cb <b>PAPER TRADING REPORT</b>",
            "",
            f"Paused: {manager.get('paused')}",
            f"Telegram enabled: {manager.get('telegram_enabled')}",
            f"Equity: {executor.get('equity', 0):.2f}",
            f"Cash: {executor.get('cash', 0):.2f}",
            f"Drawdown: {executor.get('drawdown', 0) * 100:.2f}%",
            f"Daily loss: {executor.get('dailyloss', executor.get('daily_loss', 0)) * 100:.2f}%",
            f"Open positions: {executor.get('openpositions', executor.get('open_positions', 0))}",
            f"Realized PnL: {executor.get('realizedpnl', executor.get('realized_pnl', 0)):.2f}",
            f"Pause reason: {executor.get('pausereason', executor.get('pause_reason', '')) or 'none'}",
            f"Paused until: {executor.get('pauseduntil', executor.get('paused_until', '')) or 'none'}",
        ]
        return "\n".join(lines)

    def render_status_telegram(self) -> str:
        """Risposta formattata per /status: equity, drawdown, posizioni, regime BTC."""
        s = self.status()
        btc_price = self.last_prices.get("BTCUSDT", self.last_prices.get("BTC", 0.0))

        # Tenta di recuperare il regime dal bundle se disponibile
        regime_str = "unknown"
        if INTEGRATION_BUNDLE.exists():
            try:
                bundle = json.loads(INTEGRATION_BUNDLE.read_text(encoding="utf-8"))
                feed = bundle.get("feed_snapshot") or {}
                regime_str = str(feed.get("regime", feed.get("btc_regime", "unknown")))
            except Exception:
                pass

        lines = [
            "\U0001f4ca <b>STATUS</b>",
            f"\U0001f4b0 Equity: <b>{s['equity']:.2f} USDT</b>",
            f"\U0001f4c9 Drawdown: {s['drawdown'] * 100:.2f}%",
            f"\U0001f4c8 Daily loss: {s['dailyloss'] * 100:.2f}%",
            f"\U0001f4bc Open positions: {s['openpositions']}",
            f"\U0001f534 Paused: {s['paused'] or s['manager_paused']}",
            f"\U0001f7e1 BTC price: {btc_price:.2f} USDT" if btc_price else "",
            f"\U0001f30d BTC regime: {regime_str}",
            f"\u23f0 Updated: {self._now_iso()[:19]}Z",
        ]
        return "\n".join(l for l in lines if l)

    def render_log_tail(self, n: int = LOG_TAIL_LINES) -> str:
        """Restituisce gli ultimi n log da paper_trading_log.txt."""
        # Cerca anche nei log alternativi
        candidates = [
            PAPER_TRADING_LOG,
            OUT / "paper_trading_log.txt",
            OUT / "integration_manager_log.jsonl",
        ]
        log_path = None
        for c in candidates:
            if c.exists():
                log_path = c
                break

        if log_path is None:
            return "\u26a0\ufe0f No log file found."

        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-n:] if len(lines) >= n else lines
            # Per file JSONL mostra solo il campo 'event'
            if log_path.suffix == ".jsonl":
                parsed = []
                for line in tail:
                    try:
                        obj = json.loads(line)
                        ts = obj.get("ts", obj.get("timestamp", ""))
                        ev = obj.get("event", line)
                        parsed.append(f"{str(ts)[:19]} | {ev}" if ts else ev)
                    except Exception:
                        parsed.append(line)
                tail = parsed
            header = f"\U0001f4dc <b>Last {len(tail)} log lines</b> ({log_path.name})"
            return header + "\n" + "\n".join(tail)
        except Exception as e:
            return f"\u26a0\ufe0f Log read error: {e}"

    def export_bundle(self) -> dict:
        feed_snapshot = None
        if FEED_STATE_JSON.exists():
            try:
                feed_snapshot = json.loads(FEED_STATE_JSON.read_text(encoding="utf-8"))
            except Exception as e:
                self.log(f"Feed snapshot read failed: {e}")

        data = {
            "manager": {
                "paused": self.paused,
                "last_prices": self.last_prices,
                "telegram_enabled": self.telegram_enabled,
                "telegram_chat_id_configured": bool(TELEGRAM_CHAT_ID),
            },
            "executor": self.executor.status(),
            "positions": [vars(p) for p in self.executor.positions.values()],
            "trades": [vars(t) for t in self.executor.trade_history[-20:]],
            "feed_snapshot": feed_snapshot,
            "updated_at": self._now_iso(),
        }
        self._atomic_write_text(INTEGRATION_BUNDLE, json.dumps(data, indent=2))
        return data

    async def cycle_once(self) -> None:
        prices = await self.feed.run_once()
        self.sync_prices_to_executor(prices)
        self.maybe_trade()
        self.export_bundle()
        self.notify_new_opens_and_closes()

        summary = self.summary_text()
        if summary != self.last_summary_text:
            self.log(summary)
            self.last_summary_text = summary
            self.save_state()

    def pause(self) -> None:
        self.paused = True
        self.executor.paused = True
        self.executor.save_state()
        self.save_state()
        self.log("Paused by command")
        if self.telegram_enabled:
            self.send_telegram_message("\u23f8 Manager paused.")

    def resume(self) -> None:
        self.paused = False
        if hasattr(self.executor, "resume_trading"):
            self.executor.resume_trading()
        else:
            self.executor.paused = False
            self.executor.save_state()

        self.save_state()
        self.log("Resumed by command")
        if self.telegram_enabled:
            self.send_telegram_message("\u25b6\ufe0f Manager resumed.")

    async def process_telegram_command(
        self, text: str, from_chat_id: Optional[str] = None
    ) -> Optional[str]:
        cmd = (text or "").strip().lower().split()[0] if text.strip() else ""

        # -----------------------------------------------------------------
        # Comandi pubblici (solo lettura)
        # -----------------------------------------------------------------
        if cmd in ("/start", "start"):
            return (
                "\U0001f916 <b>Bot online.</b>\n"
                "Comandi disponibili:\n"
                "/status \u2014 equity, drawdown, posizioni, regime BTC\n"
                "/log \u2014 ultimi 20 log\n"
                "/report \u2014 report runtime completo\n"
                "/pause \u2014 pausa manuale (solo chat autorizzata)\n"
                "/resume \u2014 riprendi (solo chat autorizzata)\n"
                "/positions \u2014 posizioni aperte\n"
                "/trades \u2014 ultimi trade chiusi\n"
                "/help \u2014 questo messaggio"
            )

        if cmd in ("/help", "help"):
            return (
                "\U0001f4cb <b>Comandi disponibili:</b>\n"
                "/status \u2014 equity, drawdown, posizioni, regime BTC\n"
                "/log \u2014 ultimi 20 log\n"
                "/report \u2014 report runtime completo\n"
                "/pause \u2014 pausa manuale (solo chat autorizzata)\n"
                "/resume \u2014 riprendi (solo chat autorizzata)\n"
                "/positions \u2014 posizioni aperte\n"
                "/trades \u2014 ultimi trade chiusi"
            )

        if cmd in ("/status", "status"):
            return self.render_status_telegram()

        if cmd in ("/log", "log"):
            return self.render_log_tail(LOG_TAIL_LINES)

        if cmd in ("/report", "report"):
            return self.render_report()

        if cmd in ("/positions", "positions"):
            return self.render_positions()

        if cmd in ("/trades", "trades"):
            return self.render_trades()

        # -----------------------------------------------------------------
        # Comandi critici: solo TELEGRAM_ALLOWED_CHAT_ID
        # -----------------------------------------------------------------
        if cmd in ("/pause", "pause", "/resume", "resume", "/cycle", "cycle"):
            if TELEGRAM_ALLOWED_CHAT_ID and str(from_chat_id) != str(TELEGRAM_ALLOWED_CHAT_ID):
                return "\u26d4 Accesso negato: comando riservato alla chat autorizzata."

            if cmd in ("/pause", "pause"):
                self.pause()
                return "\u23f8 Pausa attivata. Il bot non eseguir\u00e0 nuovi trade."

            if cmd in ("/resume", "resume"):
                self.resume()
                return "\u25b6\ufe0f Ripresa confermata. Il bot \u00e8 di nuovo operativo."

            if cmd in ("/cycle", "cycle"):
                try:
                    await self.cycle_once()
                    return "\u2705 Ciclo completato."
                except Exception as e:
                    return f"\u26a0\ufe0f Cycle error: {e}"

        return "\u2753 Comando sconosciuto. Usa /help per la lista."

    async def telegram_loop(self) -> None:
        """Long-polling loop Telegram. Gira in asyncio.gather() con manager_loop."""
        if not self.telegram_enabled:
            self.log("Telegram disabled: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID mancanti")
            return

        self.log("Telegram polling loop avviato")

        while True:
            try:
                updates = await asyncio.to_thread(self.get_telegram_updates)

                for upd in updates:
                    update_id = upd.get("update_id")
                    if update_id is not None:
                        self.telegram_offset = update_id + 1
                        self.save_state()

                    message = upd.get("message", {})
                    chat = message.get("chat", {})
                    chat_id = str(chat.get("id", ""))

                    # Filtro: accetta solo messaggi dal CHAT_ID configurato
                    if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                        continue

                    text = message.get("text", "")
                    if not text:
                        continue

                    response = await self.process_telegram_command(
                        text, from_chat_id=chat_id
                    )
                    if response:
                        await asyncio.to_thread(
                            self.send_telegram_message, response, chat_id
                        )

            except Exception as e:
                self.log(f"Telegram loop error: {e}")

            await asyncio.sleep(TELEGRAM_POLL_SLEEP)

    async def manager_loop(self, poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        self.log(f"Integration loop started (poll_seconds={poll_seconds})")

        while True:
            try:
                await self.cycle_once()
            except Exception as e:
                err = f"Manager error: {e}"
                self.log(err)
                if self.telegram_enabled:
                    await asyncio.to_thread(self.send_telegram_message, err)

            await asyncio.sleep(poll_seconds)

    async def run_forever(self, poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        """Modalit\u00e0 persistente: manager_loop + telegram_loop in parallelo.
        Usata quando il file viene eseguito direttamente: python integration_manager.py
        Il bot Telegram NON blocca il loop di trading.
        Se il bot Telegram cade, il runner continua.
        """
        tasks = [asyncio.create_task(self.manager_loop(poll_seconds=poll_seconds))]

        if self.telegram_enabled:
            tasks.append(asyncio.create_task(self.telegram_loop()))
            self.log("run_forever: manager + telegram in parallelo")
        else:
            self.log("run_forever: solo manager (Telegram disabilitato)")

        # gather con return_exceptions=True: se telegram_loop crasha,
        # manager_loop continua a girare.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                self.log(f"Task terminato con errore: {r}")

    async def run_budgeted(self, run_budget_seconds: int = RUN_BUDGET_SECONDS) -> None:
        """Modalit\u00e0 cron/GitHub Actions: esegue cicli fino al budget temporale.
        Il loop Telegram NON viene avviato in questa modalit\u00e0 (non persistente).
        """
        started_at = datetime.now(timezone.utc)
        deadline_ts = asyncio.get_running_loop().time() + max(
            1, run_budget_seconds - SAFETY_MARGIN_SECONDS
        )

        self.log(
            f"Budgeted run started (budget={run_budget_seconds}s, "
            f"sleep={RUN_SLEEP_SECONDS}s, safety_margin={SAFETY_MARGIN_SECONDS}s)"
        )

        cycle_count = 0

        while True:
            now_ts = asyncio.get_running_loop().time()
            if now_ts >= deadline_ts:
                break

            try:
                await self.cycle_once()
                cycle_count += 1
            except Exception as e:
                err = f"Manager error: {e}"
                self.log(err)
                if self.telegram_enabled:
                    await asyncio.to_thread(self.send_telegram_message, err)

            now_ts = asyncio.get_running_loop().time()
            if now_ts >= deadline_ts:
                break

            remaining = deadline_ts - now_ts
            sleep_for = min(RUN_SLEEP_SECONDS, max(0, remaining))
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        self.export_bundle()
        self.executor.export_runtime_report()
        self.executor.save_state()
        self.save_state()

        self.log(
            f"Budgeted run finished | cycles={cycle_count} | duration={duration:.1f}s"
        )


async def _main_standalone() -> None:
    """Entrypoint per `python integration_manager.py`.
    Avvia run_forever() con manager + Telegram in parallelo.
    Fallback silente se il token manca: solo manager, nessun crash.
    """
    if not TELEGRAM_BOT_TOKEN:
        print(
            "[integration_manager] ATTENZIONE: TELEGRAM_BOT_TOKEN non trovato in .env. "
            "Il bot Telegram non verr\u00e0 avviato. Il runner continua normalmente."
        )
    manager = IntegrationManager()
    await manager.run_forever()


async def _main_budgeted() -> None:
    manager = IntegrationManager()
    await manager.run_budgeted(run_budget_seconds=RUN_BUDGET_SECONDS)


if __name__ == "__main__":
    import sys
    # python integration_manager.py --budgeted  => modalit\u00e0 cron
    # python integration_manager.py             => modalit\u00e0 persistente con Telegram
    budgeted_mode = "--budgeted" in sys.argv
    entry = _main_budgeted if budgeted_mode else _main_standalone
    try:
        asyncio.run(entry())
    except KeyboardInterrupt:
        print("[integration_manager] Stopped by user")
