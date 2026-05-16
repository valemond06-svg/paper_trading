import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests


OUT = Path("output")
OUT.mkdir(exist_ok=True)

FEED_STATE_JSON = OUT / "price_feed_state.json"
FEED_LOG = OUT / "price_feed_log.txt"

BINANCE_DATA_API_BASE = "https://data-api.binance.vision"
REQUEST_TIMEOUT = 20


@dataclass
class FeedSnapshot:
    timestamp: str
    prices: Dict[str, float]
    source: str


class PriceFeedAdapter:
    def __init__(self, exchange_id: str = "binance-data", poll_seconds: int = 15):
        self.exchange_id = exchange_id
        self.poll_seconds = poll_seconds
        self.asset_map = {
            "BNBUSDT": "BNBUSDT",
            "BTCUSDT": "BTCUSDT",
        }
        self.session = requests.Session()
        self.last_snapshot: Optional[FeedSnapshot] = None
        self.log(f"Adapter initialized for {exchange_id}")

    def log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} | {message}"
        with FEED_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    def fetch_all_prices(self) -> Dict[str, float]:
        resp = self.session.get(
            f"{BINANCE_DATA_API_BASE}/api/v3/ticker/price",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            raise ValueError(f"Unexpected ticker payload: {data}")

        prices_by_symbol = {}
        for item in data:
            symbol = item.get("symbol")
            price = item.get("price")
            if symbol and price is not None:
                prices_by_symbol[symbol] = float(price)

        return prices_by_symbol

    def fetch_prices_rest(self) -> Dict[str, float]:
        all_prices = self.fetch_all_prices()
        prices: Dict[str, float] = {}

        for asset, symbol in self.asset_map.items():
            if symbol not in all_prices:
                raise ValueError(f"Missing price for symbol {symbol}")
            prices[asset] = all_prices[symbol]

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
        FEED_STATE_JSON.write_text(json.dumps(asdict(snap), indent=2), encoding="utf-8")

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