import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import ccxt

OUT = Path("output")
OUT.mkdir(exist_ok=True)

FEEDSTATEJSON = OUT / "price_feed_state.json"
FEEDLOG = OUT / "price_feed_log.txt"


@dataclass
class FeedSnapshot:
    timestamp: str
    prices: Dict[str, float]
    source: str


class PriceFeedAdapter:
    def __init__(self, exchange_id: str = "binance", poll_seconds: int = 15):
        self.exchange_id = exchange_id
        self.poll_seconds = poll_seconds
        self.asset_map = {
            "BNBUSDT": "BNB/USDT",
            "BTCUSDT": "BTC/USDT",
        }
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.last_snapshot: Optional[FeedSnapshot] = None
        self.log(f"Adapter initialized for {exchange_id}")

    def log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        with FEEDLOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def fetch_prices_rest(self) -> Dict[str, float]:
        prices = {}
        for asset, symbol in self.asset_map.items():
            ticker = self.exchange.fetch_ticker(symbol)
            last = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
            if last is None:
                raise ValueError(f"No price for symbol {symbol}")
            prices[asset] = float(last)
        return prices

    async def fetch_prices_async(self) -> Dict[str, float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_prices_rest)

    def save_snapshot(self, prices: Dict[str, float], source: str) -> None:
        snap = FeedSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            prices=prices,
            source=source,
        )
        self.last_snapshot = snap
        FEEDSTATEJSON.write_text(json.dumps(asdict(snap), indent=2), encoding="utf-8")

    def get_latest_prices(self) -> Dict[str, float]:
        if self.last_snapshot:
            return self.last_snapshot.prices
        return self.fetch_prices_rest()

    async def run_once(self) -> Dict[str, float]:
        prices = await self.fetch_prices_async()
        self.save_snapshot(prices, source=self.exchange_id)
        self.log(f"Updated prices: {prices}")
        return prices

    async def run_forever(self) -> None:
        self.log("Starting price feed loop")
        while True:
            try:
                await self.run_once()
            except Exception as e:
                self.log(f"Price feed error: {e}")
            await asyncio.sleep(self.poll_seconds)

    def summary_text(self) -> str:
        if not self.last_snapshot:
            return "No price snapshot yet."
        lines = [
            "PRICE FEED SNAPSHOT",
            f"Source: {self.last_snapshot.source}",
            f"Timestamp: {self.last_snapshot.timestamp}",
        ]
        for asset, price in self.last_snapshot.prices.items():
            lines.append(f"{asset}: {price:.4f}")
        return "\n".join(lines)