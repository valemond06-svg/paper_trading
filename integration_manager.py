import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
from dotenv import load_dotenv

from price_feed_adapter import PriceFeedAdapter
from paper_trading_executor import PaperTradingBot

load_dotenv()

OUT = Path("output")
OUT.mkdir(exist_ok=True)

MANAGER_STATE = OUT / "integration_manager_state.json"
MANAGER_LOG = OUT / "integration_manager_log.txt"
FEED_STATE_JSON = OUT / "price_feed_state.json"
INTEGRATION_BUNDLE = OUT / "integration_bundle.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAMBOTTOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAMCHATID")

DEFAULT_POLL_SECONDS = 5
TELEGRAM_TIMEOUT = 20
TELEGRAM_LONG_POLL_TIMEOUT = 20
TELEGRAM_POLL_SLEEP = 1.0
RUN_BUDGET_SECONDS = 270
RUN_SLEEP_SECONDS = DEFAULT_POLL_SECONDS
SAFETY_MARGIN_SECONDS = 10


class IntegrationManager:
    def __init__(self):
        self.feed = PriceFeedAdapter()
        self.executor = PaperTradingBot()
        self.executor.load_state()

        self.paused = False
        self.last_prices: Dict[str, float] = {}

        self.telegram_enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        self.telegram_offset: Optional[int] = None

        self.notified_trade_ids: Set[str] = set()
        self.notified_open_symbols: Set[str] = set()

        self.load_state()
        self._bootstrap_notification_state()
        self.log("Integration manager initialized")

    def log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        with MANAGER_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def load_state(self) -> None:
        if not MANAGER_STATE.exists():
            return

        state = json.loads(MANAGER_STATE.read_text(encoding="utf-8"))
        self.paused = bool(state.get("paused", False))
        self.last_prices = state.get("last_prices", {}) or state.get("lastprices", {}) or {}
        self.notified_trade_ids = set(state.get("notified_trade_ids", []))
        self.notified_open_symbols = set(state.get("notified_open_symbols", []))
        self.telegram_offset = state.get("telegram_offset")

    def save_state(self) -> None:
        state = {
            "paused": self.paused,
            "last_prices": self.last_prices,
            "notified_trade_ids": sorted(self.notified_trade_ids),
            "notified_open_symbols": sorted(self.notified_open_symbols),
            "telegram_offset": self.telegram_offset,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        MANAGER_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _bootstrap_notification_state(self) -> None:
        if not self.notified_open_symbols:
            self.notified_open_symbols = set(self.executor.positions.keys())

        for trade in self.executor.trade_history:
            trade_id = getattr(trade, "trade_id", None)
            if trade_id:
                self.notified_trade_ids.add(trade_id)

    def telegram_api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

    def send_telegram_message(self, text: str) -> bool:
        if not self.telegram_enabled:
            return False

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4000],
        }

        try:
            resp = requests.post(
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
            resp = requests.get(
                self.telegram_api_url("getUpdates"),
                params=payload,
                timeout=TELEGRAM_LONG_POLL_TIMEOUT + 5,
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
        self.save_state()

    def maybe_trade(self) -> None:
        if self.paused:
            self.log("Manager paused")
            return

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
            self.send_telegram_message(self._format_open_message(symbol))
            self.notified_open_symbols.add(symbol)

        closed_symbols = self.notified_open_symbols - current_open_symbols
        if closed_symbols:
            self.notified_open_symbols = current_open_symbols.copy()

        for trade in self.executor.trade_history:
            trade_id = getattr(trade, "trade_id", None)
            if not trade_id or trade_id in self.notified_trade_ids:
                continue
            self.send_telegram_message(self._format_close_message(trade))
            self.notified_trade_ids.add(trade_id)

        self.save_state()

    async def cycle_once(self) -> None:
        prices = await self.feed.run_once()
        self.sync_prices_to_executor(prices)
        self.maybe_trade()
        self.export_bundle()
        self.notify_new_opens_and_closes()
        self.log(self.summary_text())

    def pause(self) -> None:
        self.paused = True
        self.executor.paused = True
        self.executor.save_state()
        self.save_state()
        self.log("Paused by command")
        if self.telegram_enabled:
            self.send_telegram_message("Manager paused.")

    def resume(self) -> None:
        self.paused = False
        self.executor.paused = False
        self.executor.save_state()
        self.save_state()
        self.log("Resumed by command")
        if self.telegram_enabled:
            self.send_telegram_message("Manager resumed.")

    def status(self) -> dict:
        status = self.executor.status()
        status["manager_paused"] = self.paused
        status["last_price_symbols"] = list(self.last_prices.keys())
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
            "PAPER TRADING REPORT",
            "",
            f"Paused: {manager.get('paused')}",
            f"Telegram enabled: {manager.get('telegram_enabled')}",
            f"Equity: {executor.get('equity', 0):.2f}",
            f"Cash: {executor.get('cash', 0):.2f}",
            f"Drawdown: {executor.get('drawdown', 0) * 100:.2f}%",
            f"Daily loss: {executor.get('dailyloss', 0) * 100:.2f}%",
            f"Open positions: {executor.get('openpositions', 0)}",
            f"Realized PnL: {executor.get('realizedpnl', 0):.2f}",
        ]
        return "\n".join(lines)

    def export_bundle(self) -> dict:
        data = {
            "manager": {
                "paused": self.paused,
                "last_prices": self.last_prices,
                "telegram_enabled": self.telegram_enabled,
            },
            "executor": self.executor.status(),
            "positions": [p.__dict__ for p in self.executor.positions.values()],
            "trades": [t.__dict__ for t in self.executor.trade_history[-20:]],
            "feed_snapshot": (
                json.loads(FEED_STATE_JSON.read_text(encoding="utf-8"))
                if FEED_STATE_JSON.exists()
                else None
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        INTEGRATION_BUNDLE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    async def process_telegram_command(self, text: str) -> Optional[str]:
        cmd = (text or "").strip().lower()

        if cmd in ("/start", "start"):
            return (
                "Bot online.\n"
                "Commands: /status /positions /trades /pause /resume /report /cycle /help"
            )

        if cmd in ("/help", "help"):
            return "Commands: /status /positions /trades /pause /resume /report /cycle /help"

        if cmd in ("/status", "status"):
            return self.summary_text()

        if cmd in ("/positions", "positions"):
            return self.render_positions()

        if cmd in ("/trades", "trades"):
            return self.render_trades()

        if cmd in ("/pause", "pause"):
            self.pause()
            return "Paused."

        if cmd in ("/resume", "resume"):
            self.resume()
            return "Resumed."

        if cmd in ("/report", "report"):
            return self.render_report()

        if cmd in ("/cycle", "cycle"):
            try:
                await self.cycle_once()
                return "Cycle completed."
            except Exception as e:
                return f"Cycle error: {e}"

        return "Unknown command. Use /help"

    async def telegram_loop(self) -> None:
        if not self.telegram_enabled:
            self.log("Telegram disabled: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
            return

        self.log("Telegram loop started")

        while True:
            try:
                updates = await asyncio.to_thread(self.get_telegram_updates)

                for upd in updates:
                    update_id = upd.get("update_id")
                    if update_id is not None:
                        self.telegram_offset = update_id + 1

                    message = upd.get("message", {})
                    chat = message.get("chat", {})
                    chat_id = str(chat.get("id", ""))

                    if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                        continue

                    text = message.get("text", "")
                    if not text:
                        continue

                    response = await self.process_telegram_command(text)
                    if response:
                        await asyncio.to_thread(self.send_telegram_message, response)

                self.save_state()
            except Exception as e:
                self.log(f"Telegram loop error: {e}")

            await asyncio.sleep(TELEGRAM_POLL_SLEEP)

    async def manager_loop(self, poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        self.log(f"Integration loop started (poll_seconds={poll_seconds})")

        if self.telegram_enabled:
            await asyncio.to_thread(
                self.send_telegram_message,
                f"Integration manager started.\nPolling every {poll_seconds} seconds.",
            )

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
        if self.telegram_enabled:
            await asyncio.gather(
                self.manager_loop(poll_seconds=poll_seconds),
                self.telegram_loop(),
            )
        else:
            await self.manager_loop(poll_seconds=poll_seconds)

    async def run_budgeted(self, run_budget_seconds: int = RUN_BUDGET_SECONDS) -> None:
        started_at = datetime.now(timezone.utc)
        deadline_ts = asyncio.get_running_loop().time() + max(
            1, run_budget_seconds - SAFETY_MARGIN_SECONDS
        )

        self.log(
            f"Budgeted run started (budget={run_budget_seconds}s, "
            f"sleep={RUN_SLEEP_SECONDS}s, safety_margin={SAFETY_MARGIN_SECONDS}s)"
        )

        if self.telegram_enabled:
            await asyncio.to_thread(
                self.send_telegram_message,
                f"Integration manager started.\n"
                f"Budget: {run_budget_seconds}s\n"
                f"Poll: {RUN_SLEEP_SECONDS}s",
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

        final_msg = (
            f"Budgeted run finished.\n"
            f"Cycles: {cycle_count}\n"
            f"Duration: {duration:.1f}s\n"
            f"{self.summary_text()}"
        )

        self.log(final_msg.replace("\n", " | "))
        self.save_state()

        if self.telegram_enabled:
            await asyncio.to_thread(self.send_telegram_message, final_msg)


async def _main() -> None:
    manager = IntegrationManager()
    await manager.run_budgeted(run_budget_seconds=RUN_BUDGET_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("Stopped by user")