import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

OUT = Path("output")
OUT.mkdir(exist_ok=True)

PLANJSON = OUT / "paper_trading_plan.json"
REPORTJSON = OUT / "paper_trading_report.json"
STATEJSON  = OUT / "paper_trading_state.json"

MAX_OPEN_TRADES   = 3
DEFAULT_EQUITY    = 10_000.0
DAILY_LOSS_LIMIT  = 0.03   # 3% drawdown giornaliero → pausa
MAX_POSITION_PCT  = 0.40   # max 40% del capitale per posizione
COOLDOWN_SECONDS  = 3_600  # 1 h di cooldown dopo pausa


@dataclass
class Position:
    symbol: str
    asset: str
    side: str
    entry_price: float
    quantity: float
    stop_price: float
    take_profit: float
    strategy: str
    timeframe: str
    opened_at: str
    trailing_stop: bool = False
    highest_price: float = 0.0

    # ------------------------------------------------------------------ #
    @property
    def value(self) -> float:
        return self.quantity * self.entry_price          # book value

    def current_value(self, price: float) -> float:
        return self.quantity * price

    def pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.quantity

    def pnl_pct(self, price: float) -> float:
        return (price - self.entry_price) / self.entry_price

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(
            symbol       = d["symbol"],
            asset        = d.get("asset", d["symbol"].replace("USDT", "")),
            side         = d.get("side", "long"),
            entry_price  = float(d["entry_price"]),
            quantity     = float(d["quantity"]),
            stop_price   = float(d["stop_price"]),
            take_profit  = float(d["take_profit"]),
            strategy     = d.get("strategy", ""),
            timeframe    = d.get("timeframe", ""),
            opened_at    = d.get("opened_at", ""),
            trailing_stop = bool(d.get("trailing_stop", False)),
            highest_price = float(d.get("highest_price", d.get("entry_price", 0.0))),
        )


class PaperTradingBot:
    """
    Executor per il paper trading.
    Gestisce equity, posizioni aperte, risk management e pausa automatica.
    """

    def __init__(self, plan_path: Path) -> None:
        self.plan_path   = plan_path
        self.equity      = DEFAULT_EQUITY
        self.cash        = DEFAULT_EQUITY
        self.positions: Dict[str, Position] = {}
        self.trades: List[dict]             = []
        self.selected: List[dict]           = []
        self.last_prices: Dict[str, float]  = {}

        self.paused        = False
        self.pause_reason  = ""
        self.paused_until  = ""

        self._daily_baseline: float = DEFAULT_EQUITY
        self._daily_baseline_date: str = ""
        self._risk_stop_active: bool = False

        self._load_plan()

    # ------------------------------------------------------------------ #
    # Utility                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def parse_dt(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def log(self, msg: str) -> None:
        ts = self.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"{ts} | {msg}")

    # ------------------------------------------------------------------ #
    # Plan                                                                 #
    # ------------------------------------------------------------------ #

    def _load_plan(self) -> None:
        if not self.plan_path.exists():
            self.selected = []
            return
        with open(self.plan_path) as f:
            data = json.load(f)
        self.selected = data.get("selected", [])

    # ------------------------------------------------------------------ #
    # State persistence                                                    #
    # ------------------------------------------------------------------ #

    def save_state(self) -> None:
        state = {
            "equity"         : self.equity,
            "cash"           : self.cash,
            "paused"         : self.paused,
            "pause_reason"   : self.pause_reason,
            "paused_until"   : self.paused_until,
            "pauseduntil"    : self.paused_until,       # alias legacy
            "daily_baseline" : self._daily_baseline,
            "daily_baseline_date": self._daily_baseline_date,
            "risk_stop_active": self._risk_stop_active,
            "positions"      : {k: v.to_dict() for k, v in self.positions.items()},
            "trades"         : self.trades,
            "last_prices"    : self.last_prices,
        }
        with open(STATEJSON, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def load_state(self) -> None:
        if not STATEJSON.exists():
            return
        with open(STATEJSON) as f:
            state = json.load(f)

        self.equity = float(state.get("equity", DEFAULT_EQUITY))
        self.cash   = float(state.get("cash",   self.equity))
        self.paused       = bool(state.get("paused", False))
        self.pause_reason = str(state.get("pause_reason", ""))
        self.paused_until = str(state.get("paused_until", state.get("pauseduntil", "")) or "")
        self._daily_baseline      = float(state.get("daily_baseline", self.equity))
        self._daily_baseline_date = str(state.get("daily_baseline_date", ""))
        self._risk_stop_active    = bool(state.get("risk_stop_active", self.paused))

        raw_pos = state.get("positions", {})
        self.positions = {k: Position.from_dict(v) for k, v in raw_pos.items()}
        self.trades      = state.get("trades", [])
        self.last_prices = state.get("last_prices", {})

    # ------------------------------------------------------------------ #
    # Equity                                                               #
    # ------------------------------------------------------------------ #

    def update_equity(self) -> None:
        pos_value = sum(
            pos.current_value(self.last_prices.get(sym, pos.entry_price))
            for sym, pos in self.positions.items()
        )
        self.equity = self.cash + pos_value

    # ------------------------------------------------------------------ #
    # Daily baseline                                                       #
    # ------------------------------------------------------------------ #

    def maybe_reset_daily_baseline(self) -> None:
        today = self.now_utc().strftime("%Y-%m-%d")
        if self._daily_baseline_date == today:
            return

        if self.paused and self.pause_reason == "daily_loss_stop":
            paused_until_dt = self.parse_dt(self.paused_until)
            if paused_until_dt and self.now_utc() >= paused_until_dt:
                self.paused = False
                self.pause_reason = ""
                self.paused_until = ""

        self._daily_baseline      = self.equity
        self._daily_baseline_date = today
        self._risk_stop_active    = False
        self.log(f"daily baseline reset: {self.equity:.2f} ({today})")

    # ------------------------------------------------------------------ #
    # Risk management                                                      #
    # ------------------------------------------------------------------ #

    def maybe_release_pause(self) -> None:
        if not self.paused:
            return
        paused_until_dt = self.parse_dt(self.paused_until)
        if paused_until_dt is None:
            return
        if self.now_utc() >= paused_until_dt:
            self.log(f"pause released (was: {self.pause_reason})")
            self.paused       = False
            self.pause_reason = ""
            self.paused_until = ""

    def _activate_pause(self, reason: str, cooldown_seconds: int = COOLDOWN_SECONDS) -> None:
        self.paused       = True
        self.pause_reason = reason
        self._risk_stop_active = True
        self.paused_until = (self.now_utc() + timedelta(seconds=cooldown_seconds)).isoformat()
        self.log(f"bot PAUSED | reason={reason} until={self.paused_until}")

    def should_pause(self) -> bool:
        """
        Ritorna True e attiva la pausa se il drawdown giornaliero supera
        DAILY_LOSS_LIMIT.  NON viene chiamata se il bot è già in pausa
        (vedi process_price).
        """
        if self._daily_baseline <= 0:
            return False
        drawdown = (self._daily_baseline - self.equity) / self._daily_baseline
        if drawdown >= DAILY_LOSS_LIMIT:
            self._activate_pause("daily_loss_stop")
            return True
        return False

    # ------------------------------------------------------------------ #
    # run_cycle (entry point principale del runner)                        #
    # ------------------------------------------------------------------ #

    def run_cycle(self, price_map: Dict[str, float]) -> None:
        self.maybe_release_pause()
        self.maybe_reset_daily_baseline()

        if self.paused:
            return

        self.update_equity()
        if self.should_pause():
            return

        if len(self.positions) >= MAX_OPEN_TRADES:
            self.save_state()
            return

        selected = sorted(
            self.selected,
            key=lambda r: float(r.get("targetweight", r.get("target_weight", 0.0))),
            reverse=True,
        )
        for row in selected:
            sym = self.symbol_for_row(row)
            price = price_map.get(sym)
            if price is None:
                continue
            self.last_prices[sym] = float(price)

        self.save_state()

    # ------------------------------------------------------------------ #
    # Symbol helper                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def symbol_for_row(row: dict) -> str:
        sym = row.get("symbol") or row.get("asset", "")
        if not sym.endswith("USDT"):
            sym = sym + "USDT"
        return sym.upper()

    # ------------------------------------------------------------------ #
    # Position management                                                  #
    # ------------------------------------------------------------------ #

    def open_position(self, row: dict, price: float) -> Optional[Position]:
        if self.paused:
            return None
        if len(self.positions) >= MAX_OPEN_TRADES:
            return None

        asset  = row.get("asset", "").upper()
        symbol = self.symbol_for_row(row)

        if symbol in self.positions:
            return None

        risk_pct   = float(row.get("risk_per_trade", 0.01))
        risk_amt   = self.equity * risk_pct
        stop_dist  = price * 0.02          # 2% default stop
        quantity   = risk_amt / stop_dist
        cost       = quantity * price

        # Clip a MAX_POSITION_PCT
        max_cost   = self.equity * MAX_POSITION_PCT
        if cost > max_cost:
            quantity = max_cost / price
            cost     = max_cost

        if cost > self.cash:
            return None

        stop_price  = price * (1 - 0.02)
        take_profit = price * (1 + 0.04)

        pos = Position(
            symbol      = symbol,
            asset       = asset,
            side        = "long",
            entry_price = price,
            quantity    = quantity,
            stop_price  = stop_price,
            take_profit = take_profit,
            strategy    = row.get("strategy", ""),
            timeframe   = row.get("timeframe", ""),
            opened_at   = self.now_utc().isoformat(),
            highest_price = price,
        )
        self.positions[symbol] = pos
        self.cash -= cost
        self.update_equity()
        self.log(
            f"OPEN {symbol} @ {price:.2f} | qty={quantity:.6f} "
            f"stop={stop_price:.2f} tp={take_profit:.2f} strategy={row.get('strategy','')}"
        )
        self.save_state()
        return pos

    def close_position(self, symbol: str, price: float, reason: str = "manual") -> Optional[dict]:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        proceeds = pos.quantity * price
        pnl      = pos.pnl(price)
        self.cash   += proceeds
        self.update_equity()

        trade = {
            "id"          : str(uuid.uuid4()),
            "symbol"      : symbol,
            "asset"       : pos.asset,
            "strategy"    : pos.strategy,
            "timeframe"   : pos.timeframe,
            "side"        : pos.side,
            "entry_price" : pos.entry_price,
            "exit_price"  : price,
            "quantity"    : pos.quantity,
            "pnl"         : round(pnl, 4),
            "pnl_pct"     : round(pos.pnl_pct(price), 6),
            "reason"      : reason,
            "opened_at"   : pos.opened_at,
            "closed_at"   : self.now_utc().isoformat(),
        }
        self.trades.append(trade)
        self.log(
            f"CLOSE {symbol} @ {price:.2f} | reason={reason} "
            f"pnl={pnl:+.2f} equity={self.equity:.2f}"
        )
        self.save_state()
        return trade

    # ------------------------------------------------------------------ #
    # process_price — chiamata ad ogni tick di prezzo                     #
    # ------------------------------------------------------------------ #

    def process_price(self, symbol: str, price: float) -> None:
        self.maybe_release_pause()
        self.maybe_reset_daily_baseline()

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
        if not self.paused:   # fix: evita logging storm quando già in pausa
            self.should_pause()
        self.save_state()

    def ingest_prices(self, price_map: Dict[str, float]) -> None:
        for sym, price in price_map.items():
            self.process_price(sym, float(price))

    def maybe_rebalance(self) -> None:
        self.maybe_release_pause()
        self.maybe_reset_daily_baseline()

        if self.paused:
            return

        self.update_equity()
        if self.should_pause():
            return

        if len(self.positions) >= MAX_OPEN_TRADES:
            self.save_state()
            return

        selected = sorted(
            self.selected,
            key=lambda r: float(r.get("targetweight", r.get("target_weight", 0.0))),
            reverse=True,
        )
        for row in selected:
            sym   = self.symbol_for_row(row)
            price = self.last_prices.get(sym)
            if price is None:
                continue
            if sym not in self.positions:
                self.open_position(row, price)

        self.save_state()

    # ------------------------------------------------------------------ #
    # Emergency stop                                                       #
    # ------------------------------------------------------------------ #

    def emergency_stop(self, reason: str = "manual") -> None:
        self.log(f"EMERGENCY STOP | reason={reason}")
        for sym in list(self.positions.keys()):
            price = self.last_prices.get(sym, self.positions[sym].entry_price)
            self.close_position(sym, price, f"emergency_{reason}")
        self.paused       = False
        self.pause_reason = ""
        self.paused_until = ""
        self.save_state()

    # ------------------------------------------------------------------ #
    # Status snapshot                                                      #
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        self.update_equity()
        paused = self.paused
        return {
            "equity"        : round(self.equity, 2),
            "cash"          : round(self.cash, 2),
            "open_positions": len(self.positions),
            "total_trades"  : len(self.trades),
            "paused"        : paused,
            "pause_reason"  : self.pause_reason,
            "paused_until"  : self.paused_until,
            "pauseduntil"   : self.paused_until,
            "daily_baseline": round(self._daily_baseline, 2),
            "risk_stop_active": self._risk_stop_active,
        }
