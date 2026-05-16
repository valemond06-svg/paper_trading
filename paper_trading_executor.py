import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

OUT = Path("output")
OUT.mkdir(exist_ok=True)

PLANJSON = OUT / "paper_trading_plan.json"
REPORTJSON = OUT / "paper_trading_runtime.json"
TRADESCSV = OUT / "paper_trading_trades.csv"
STATEJSON = OUT / "paper_trading_state.json"
LOGTXT = OUT / "paper_trading_log.txt"

INITIAL_EQUITY = 1000.0
FEE_PCT = 0.001
SLIPPAGE_PCT = 0.0005
MAX_PORTFOLIO_RISK = 0.03
MAX_DRAWDOWN_STOP = 0.07
DAILY_LOSS_STOP = 0.02


@dataclass
class Position:
    symbol: str
    asset: str
    timeframe: str
    strategy: str
    side: str
    quantity: float
    entry_price: float
    stop_price: float
    take_profit: float
    opened_at: str
    target_weight: float
    risk_per_trade: float


@dataclass
class Trade:
    trade_id: str
    timestamp: str
    symbol: str
    asset: str
    timeframe: str
    strategy: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    fees: float
    reason: str


class PaperTradingBot:
    def __init__(self, plan_path: Path = PLANJSON):
        self.plan_path = plan_path
        self.state_path = STATEJSON
        self.log_path = LOGTXT
        self.trades_path = TRADESCSV

        self.plan = self.load_plan()
        self.selected = self.plan.get("selected", [])
        self.max_portfolio_risk = float(
            self.plan.get("maxportfoliorisk", self.plan.get("max_portfolio_risk", MAX_PORTFOLIO_RISK))
        )
        self.base_risk_per_trade = float(
            self.plan.get("baseriskpertrade", self.plan.get("base_risk_per_trade", 0.01))
        )

        self.cash = INITIAL_EQUITY
        self.equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY
        self.daily_start_equity = INITIAL_EQUITY
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Trade] = []
        self.last_prices: Dict[str, float] = {}
        self.paused = False
        self.consecutive_losses = 0
        self.realized_pnl = 0.0

        self.log("Bot initialized")

    def _atomic_write_text(self, path: Path, text: str) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)

    def load_plan(self) -> dict:
        if not self.plan_path.exists():
            raise FileNotFoundError(f"Missing paper trading plan: {self.plan_path}")
        return json.loads(self.plan_path.read_text(encoding="utf-8"))

    def log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def _normalize_position_dict(self, raw: dict) -> dict:
        raw = dict(raw)

        if "entryprice" in raw:
            raw["entry_price"] = raw.pop("entryprice")
        if "stopprice" in raw:
            raw["stop_price"] = raw.pop("stopprice")
        if "takeprofit" in raw:
            raw["take_profit"] = raw.pop("takeprofit")
        if "openedat" in raw:
            raw["opened_at"] = raw.pop("openedat")
        if "targetweight" in raw:
            raw["target_weight"] = raw.pop("targetweight")
        if "riskpertrade" in raw:
            raw["risk_per_trade"] = raw.pop("riskpertrade")

        return raw

    def _normalize_trade_dict(self, raw: dict) -> dict:
        raw = dict(raw)

        if "tradeid" in raw:
            raw["trade_id"] = raw.pop("tradeid")
        if "entryprice" in raw:
            raw["entry_price"] = raw.pop("entryprice")
        if "exitprice" in raw:
            raw["exit_price"] = raw.pop("exitprice")
        if "grosspnl" in raw:
            raw["gross_pnl"] = raw.pop("grosspnl")
        if "netpnl" in raw:
            raw["net_pnl"] = raw.pop("netpnl")

        return raw

    def load_state(self) -> None:
        if not self.state_path.exists():
            return

        state = json.loads(self.state_path.read_text(encoding="utf-8"))

        self.cash = float(state.get("cash", INITIAL_EQUITY))
        self.equity = float(state.get("equity", INITIAL_EQUITY))
        self.peak_equity = float(state.get("peakequity", state.get("peak_equity", INITIAL_EQUITY)))
        self.daily_start_equity = float(
            state.get("dailystartequity", state.get("daily_start_equity", INITIAL_EQUITY))
        )
        self.paused = bool(state.get("paused", False))
        self.consecutive_losses = int(
            state.get("consecutivelosses", state.get("consecutive_losses", 0))
        )
        self.realized_pnl = float(state.get("realizedpnl", state.get("realized_pnl", 0.0)))
        self.last_prices = state.get("lastprices", state.get("last_prices", {})) or {}

        self.positions = {}
        for sym, pos in state.get("positions", {}).items():
            self.positions[sym] = Position(**self._normalize_position_dict(pos))

        self.trade_history = []
        raw_trades = state.get("trade_history", state.get("tradehistory", [])) or []
        for t in raw_trades:
            self.trade_history.append(Trade(**self._normalize_trade_dict(t)))

    def save_state(self) -> None:
        state = {
            "cash": self.cash,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "daily_start_equity": self.daily_start_equity,
            "paused": self.paused,
            "consecutive_losses": self.consecutive_losses,
            "realized_pnl": self.realized_pnl,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "trade_history": [asdict(t) for t in self.trade_history],
            "last_prices": self.last_prices,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "peakequity": self.peak_equity,
            "dailystartequity": self.daily_start_equity,
            "consecutivelosses": self.consecutive_losses,
            "realizedpnl": self.realized_pnl,
            "tradehistory": [asdict(t) for t in self.trade_history],
            "lastprices": self.last_prices,
            "updatedat": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_write_text(self.state_path, json.dumps(state, indent=2))

    def save_trades(self) -> None:
        rows = [asdict(t) for t in self.trade_history]
        df = pd.DataFrame(rows)
        csv_text = df.to_csv(index=False) if not df.empty else (
            "trade_id,timestamp,symbol,asset,timeframe,strategy,side,quantity,"
            "entry_price,exit_price,gross_pnl,net_pnl,fees,reason\n"
        )
        self._atomic_write_text(self.trades_path, csv_text)

    def symbol_for_row(self, row: dict) -> str:
        return f"{row['asset']}{row['timeframe']}{row['strategy']}{row['fast']}{row['slow']}{row['regime']}"

    @property
    def available_weight(self) -> float:
        used = sum(p.target_weight for p in self.positions.values())
        return max(0.0, 1.0 - used)

    @property
    def current_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return 1.0 - self.equity / self.peak_equity

    @property
    def daily_loss(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return max(0.0, (self.daily_start_equity - self.equity) / self.daily_start_equity)

    def update_equity(self) -> None:
        pos_value = 0.0
        for sym, pos in self.positions.items():
            price = self.last_prices.get(sym)
            if price is None:
                price = self.last_prices.get(pos.asset, pos.entry_price)
            pos_value += pos.quantity * price

        self.equity = self.cash + pos_value
        self.peak_equity = max(self.peak_equity, self.equity)

    def should_pause(self) -> bool:
        if self.current_drawdown >= MAX_DRAWDOWN_STOP:
            return True
        if self.daily_loss >= DAILY_LOSS_STOP:
            return True
        return False

    def open_position(self, row: dict, price: float) -> Optional[Position]:
        if self.paused or self.should_pause():
            self.paused = True
            self.save_state()
            self.log("Trading paused by risk rules")
            return None

        symbol = self.symbol_for_row(row)
        if symbol in self.positions:
            return None

        target_weight = float(row.get("targetweight", row.get("target_weight", 0.0)))
        risk_per_trade = float(row.get("riskpertrade", row.get("risk_per_trade", self.base_risk_per_trade)))
        risk_per_trade = min(risk_per_trade, self.base_risk_per_trade)

        alloc_cash = self.equity * target_weight
        if alloc_cash <= 0 or self.cash <= 0:
            return None

        entry_price = price * (1 + SLIPPAGE_PCT)
        stop_pct = max(0.01, min(0.03, risk_per_trade * 2.0))
        tp_pct = max(0.015, min(0.06, risk_per_trade * 3.0))
        stop_price = entry_price * (1 - stop_pct)
        take_profit = entry_price * (1 + tp_pct)

        max_size_cash = min(alloc_cash, self.cash)
        if max_size_cash <= 0:
            return None

        quantity = max_size_cash / entry_price
        self.cash -= max_size_cash

        pos = Position(
            symbol=symbol,
            asset=str(row["asset"]),
            timeframe=str(row["timeframe"]),
            strategy=str(row["strategy"]),
            side="long",
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit=take_profit,
            opened_at=datetime.now(timezone.utc).isoformat(),
            target_weight=target_weight,
            risk_per_trade=risk_per_trade,
        )

        self.positions[symbol] = pos
        self.last_prices[symbol] = price
        self.last_prices[pos.asset] = price
        self.update_equity()
        self.save_state()

        self.log(
            f"OPEN {symbol} qty={quantity:.6f} entry={entry_price:.4f} "
            f"stop={stop_price:.4f} tp={take_profit:.4f} cash={self.cash:.2f}"
        )
        return pos

    def close_position(self, symbol: str, price: float, reason: str) -> Optional[Trade]:
        pos = self.positions.get(symbol)
        if pos is None:
            return None

        exit_price = price * (1 - SLIPPAGE_PCT)
        gross = pos.quantity * (exit_price - pos.entry_price)
        fees = pos.quantity * pos.entry_price * FEE_PCT + pos.quantity * exit_price * FEE_PCT
        net = gross - fees

        self.log(
            f"CLOSE {symbol} reason={reason} trigger_price={price:.4f} "
            f"exit={exit_price:.4f} stop={pos.stop_price:.4f} tp={pos.take_profit:.4f} "
            f"entry={pos.entry_price:.4f} gross={gross:.4f} net={net:.4f}"
        )

        self.cash += pos.quantity * exit_price - pos.quantity * exit_price * FEE_PCT
        self.realized_pnl += net
        self.consecutive_losses = self.consecutive_losses + 1 if net < 0 else 0

        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            asset=pos.asset,
            timeframe=pos.timeframe,
            strategy=pos.strategy,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            gross_pnl=gross,
            net_pnl=net,
            fees=fees,
            reason=reason,
        )
        self.trade_history.append(trade)
        del self.positions[symbol]

        self.update_equity()
        self.save_state()
        self.save_trades()
        self.log(
            f"CLOSE DONE {symbol} reason={reason} net={net:.4f} gross={gross:.4f} "
            f"fees={fees:.4f} equity={self.equity:.2f}"
        )
        return trade

    def process_price(self, symbol: str, price: float) -> None:
        self.last_prices[symbol] = price

        for pos_symbol, pos in list(self.positions.items()):
            if pos.asset != symbol:
                continue

            self.last_prices[pos_symbol] = price

            if price <= pos.stop_price:
                self.close_position(pos_symbol, price, "stoploss")
            elif price >= pos.take_profit:
                self.close_position(pos_symbol, price, "takeprofit")

        self.update_equity()

        if self.should_pause():
            self.paused = True
            self.save_state()
            self.log("Risk stop triggered")
        else:
            self.save_state()

    def ingest_prices(self, price_map: Dict[str, float]) -> None:
        for sym, price in price_map.items():
            self.process_price(sym, float(price))

    def maybe_rebalance(self) -> None:
        if self.paused:
            return

        self.update_equity()
        if self.daily_loss >= DAILY_LOSS_STOP:
            self.paused = True
            self.save_state()
            self.log("Daily loss stop reached")
            return

        selected = sorted(
            self.selected,
            key=lambda r: float(r.get("targetweight", r.get("target_weight", 0.0))),
            reverse=True,
        )

        for row in selected:
            symbol = self.symbol_for_row(row)
            if symbol in self.positions:
                continue
            if self.available_weight < 0.05:
                break

            asset = str(row["asset"])
            last_price = self.last_prices.get(asset)
            if last_price is None:
                continue

            self.open_position(row, last_price)

        self.save_state()

    def status(self) -> dict:
        self.update_equity()

        cash = round(self.cash, 4)
        equity = round(self.equity, 4)
        peak_equity = round(self.peak_equity, 4)
        drawdown = round(self.current_drawdown, 4)
        daily_loss = round(self.daily_loss, 4)
        paused = self.paused
        consecutive_losses = self.consecutive_losses
        open_positions = len(self.positions)
        realized_pnl = round(self.realized_pnl, 4)

        return {
            "cash": cash,
            "equity": equity,
            "peak_equity": peak_equity,
            "drawdown": drawdown,
            "daily_loss": daily_loss,
            "paused": paused,
            "consecutive_losses": consecutive_losses,
            "open_positions": open_positions,
            "realized_pnl": realized_pnl,
            "peakequity": peak_equity,
            "dailyloss": daily_loss,
            "consecutivelosses": consecutive_losses,
            "openpositions": open_positions,
            "realizedpnl": realized_pnl,
        }

    def summary_text(self) -> str:
        s = self.status()
        lines = [
            "PAPER TRADING STATUS",
            f"Equity: {s['equity']:.2f}",
            f"Cash: {s['cash']:.2f}",
            f"Drawdown: {s['drawdown'] * 100:.2f}%",
            f"Daily loss: {s['dailyloss'] * 100:.2f}%",
            f"Open positions: {s['openpositions']}",
            f"Realized PnL: {s['realizedpnl']:.2f}",
            f"Paused: {s['paused']}",
            f"Consecutive losses: {s['consecutivelosses']}",
        ]
        return "\n".join(lines)

    def export_runtime_report(self) -> None:
        data = {
            "status": self.status(),
            "positions": [asdict(p) for p in self.positions.values()],
            "trades": [asdict(t) for t in self.trade_history[-20:]],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updatedat": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_write_text(REPORTJSON, json.dumps(data, indent=2))

    def run_cycle(self, price_map: Dict[str, float]) -> None:
        self.ingest_prices(price_map)
        self.maybe_rebalance()
        self.export_runtime_report()
        self.save_state()

    def maybe_rebalance_legacy(self) -> None:
        self.maybe_rebalance()

    def ingestprices(self, price_map: Dict[str, float]) -> None:
        self.ingest_prices(price_map)

    def exportruntimereport(self) -> None:
        self.export_runtime_report()

    def savestate(self) -> None:
        self.save_state()

    def loadstate(self) -> None:
        self.load_state()

    def summarytext(self) -> str:
        return self.summary_text()

    def mayberebalance(self) -> None:
        self.maybe_rebalance()


def main() -> None:
    bot = PaperTradingBot()
    bot.load_state()
    print(bot.summary_text())
    bot.export_runtime_report()


if __name__ == "__main__":
    main()