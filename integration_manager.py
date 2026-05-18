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
from paper_trading_executor import PaperTradingBot, PLANJSON
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
RUN_BUDGET_SECONDS = 250
RUN_SLEEP_SECONDS = DEFAULT_POLL_SECONDS
SAFETY_MARGIN_SECONDS = 15
LOG_TAIL_LINES = 20


class IntegrationManager:
    def __init__(self) -> None:
        self.feed = PriceFeedAdapter()
        self.executor = PaperTradingBot(PLANJSON)
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
        ]
        open_pos = self.executor.positions
        if open_pos:
            lines.append("Open positions:")
            for sym, pos in open_pos.items():
                price = self.last_prices.get(sym, pos.entry_price)
                pnl = pos.pnl(price)
                lines.append(
                    f"  {sym}: entry={pos.entry_price:.4f} "
                    f"current={price:.4f} pnl={pnl:.4f}"
                )
        return "\n".join(lines)

    def _handle_command(self, text: str, chat_id: str) -> None:
        text = text.strip().lower()
        if text == "/status":
            self.send_telegram_message(self.summary_text(), chat_id=chat_id)
        elif text == "/pause":
            self.paused = True
            self.save_state()
            self.send_telegram_message("Manager paused.", chat_id=chat_id)
        elif text == "/resume":
            self.paused = False
            self.save_state()
            self.send_telegram_message("Manager resumed.", chat_id=chat_id)
        elif text == "/log":
            try:
                lines = MANAGER_LOG.read_text(encoding="utf-8").splitlines()
                tail = "\n".join(lines[-LOG_TAIL_LINES:])
                self.send_telegram_message(f"Last {LOG_TAIL_LINES} log lines:\n{tail}", chat_id=chat_id)
            except Exception as e:
                self.send_telegram_message(f"Error reading log: {e}", chat_id=chat_id)
        else:
            self.send_telegram_message(
                "Unknown command. Available: /status /pause /resume /log",
                chat_id=chat_id,
            )

    def process_telegram_updates(self) -> None:
        updates = self.get_telegram_updates()
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self.telegram_offset = update_id + 1

            message = update.get("message", {})
            text = message.get("text", "")
            chat = message.get("chat", {})
            chat_id = str(chat.get("id", ""))

            allowed = str(TELEGRAM_ALLOWED_CHAT_ID or "")
            if allowed and chat_id != allowed:
                continue

            if text.startswith("/"):
                self._handle_command(text, chat_id)

        if updates:
            self.save_state()

    def _maybe_send_summary(self) -> None:
        if not self.telegram_enabled:
            return
        summary = self.summary_text()
        if summary != self.last_summary_text:
            self.send_telegram_message(summary)
            self.last_summary_text = summary
            self.save_state()

    async def run_loop(self) -> None:
        self.log("Starting integration manager run loop")
        deadline = asyncio.get_event_loop().time() + RUN_BUDGET_SECONDS

        while asyncio.get_event_loop().time() < deadline - SAFETY_MARGIN_SECONDS:
            try:
                prices = self.feed.fetch_prices()
                if prices:
                    self.sync_prices_to_executor(prices)
                    self.maybe_trade()
                    self.notify_new_opens_and_closes()
                    self._maybe_send_summary()

                self.process_telegram_updates()

            except Exception as e:
                self.log(f"Loop iteration error: {e}", level="ERROR")

            await asyncio.sleep(RUN_SLEEP_SECONDS)

        self.log("Run loop budget exhausted, exiting")

    def run(self) -> None:
        asyncio.run(self.run_loop())


if __name__ == "__main__":
    IntegrationManager().run()
