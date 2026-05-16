import json
import math
from dataclasses import dataclass, asdict
from itertools import product
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
import plotly.express as px
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

OUT = Path("output")
OUT.mkdir(exist_ok=True)

ASSETS = ["AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAMES = ["1h", "4h"]

START_CAPITAL = 1000.0
FEE_RATE = 0.001
SLIPPAGE = 0.0005
MIN_TRADE_USDT = 5.0

exchange = ccxt.binance({"enableRateLimit": True})


@dataclass
class BacktestResult:
    asset: str
    timeframe: str
    strategy: str
    fast: int
    slow: int
    regime: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy: float
    net_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    sortino: float
    exposure: float
    score: float


def yfinance_symbol(asset: str) -> str:
    return asset.replace("USDT", "-USD")


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.set_index("ts")
        .resample("4h")
        .agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        .dropna()
        .reset_index()
    )
    return out


def fetch_from_yfinance(asset: str, timeframe: str = "4h", limit: int = 1500) -> pd.DataFrame:
    symbol = yfinance_symbol(asset)

    raw = yf.download(
        symbol,
        interval="1h",
        period="730d",
        auto_adjust=False,
        progress=False,
        multi_level_index=False,
    )

    if raw is None or len(raw) == 0:
        raise ValueError(f"No yfinance data for {asset}")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }).reset_index()

    ts_col = "Datetime" if "Datetime" in raw.columns else "Date"
    raw["ts"] = pd.to_datetime(raw[ts_col], utc=True)

    needed = ["ts", "open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns from yfinance: {missing}")

    df = raw[needed].copy()

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna().reset_index(drop=True)

    if timeframe == "4h":
        df = resample_4h(df)

    return df.tail(limit).reset_index(drop=True)


def fetch_ohlcv(asset: str, timeframe: str = "4h", limit: int = 1500) -> pd.DataFrame:
    symbol = asset.replace("USDT", "/USDT")
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df.dropna().reset_index(drop=True)
    except Exception:
        return fetch_from_yfinance(asset, timeframe=timeframe, limit=limit)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def build_signals(df: pd.DataFrame, fast: int, slow: int, regime: int) -> pd.Series:
    close = df["close"]
    f = sma(close, fast)
    s = sma(close, slow)
    r = sma(close, regime)

    bull = (f > s) & (close > r)
    bear = (f < s) | (close < r)

    sig = pd.Series("HOLD", index=df.index)
    sig[bull] = "BUY"
    sig[bear] = "SELL"
    return sig


def bars_per_year_for_df(df: pd.DataFrame) -> int:
    delta = df["ts"].diff().median()

    if pd.isna(delta):
        return 365 * 6
    if delta <= pd.Timedelta("1h"):
        return 365 * 24
    if delta <= pd.Timedelta("4h"):
        return 365 * 6
    return 365


def perf_stats(equity, trade_returns, exposure, bars_per_year):
    eq = pd.Series(equity).dropna()
    rets = pd.Series(trade_returns).dropna()

    net_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    years = max(len(eq) / bars_per_year, 1e-9)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0) if len(eq) > 1 else 0.0

    roll = eq.cummax()
    dd = float((eq / roll - 1.0).min()) if len(eq) else 0.0

    mean = rets.mean() if len(rets) else 0.0
    std = rets.std(ddof=0) if len(rets) > 1 else 0.0
    neg = rets[rets < 0]
    downside = neg.std(ddof=0) if len(neg) > 1 else 0.0

    sharpe = float((mean / std) * math.sqrt(bars_per_year)) if std and std > 0 else 0.0
    sortino = float((mean / downside) * math.sqrt(bars_per_year)) if downside and downside > 0 else 0.0

    return net_return, cagr, dd, sharpe, sortino, float(exposure)


def backtest(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    regime: int,
    allocation: float = 0.25,
    with_curve: bool = False,
):
    sig = build_signals(df, fast, slow, regime)

    cash = START_CAPITAL
    qty = 0.0
    entry = 0.0
    equity = []
    trade_returns = []
    trade_pnls = []
    in_pos_bars = 0
    total_bars = 0

    for i in range(len(df)):
        ts = df["ts"].iloc[i]
        px = float(df["close"].iloc[i])
        action = sig.iloc[i]

        mkt_val = qty * px
        eq = cash + mkt_val
        equity.append((ts, eq) if with_curve else eq)
        total_bars += 1

        if qty > 0:
            in_pos_bars += 1

        if action == "BUY" and qty == 0:
            target = eq * allocation
            spend = min(target, cash)
            if spend >= MIN_TRADE_USDT:
                buy_px = px * (1 + SLIPPAGE)
                fee = spend * FEE_RATE
                qty = (spend - fee) / buy_px
                cash -= spend
                entry = buy_px

        elif action == "SELL" and qty > 0:
            sell_px = px * (1 - SLIPPAGE)
            gross = qty * sell_px
            fee = gross * FEE_RATE
            net = gross - fee
            pnl = net - qty * entry

            trade_pnls.append(pnl)
            trade_returns.append(pnl / (qty * entry) if qty * entry else 0.0)

            cash += net
            qty = 0.0
            entry = 0.0

    if qty > 0:
        px = float(df["close"].iloc[-1])
        sell_px = px * (1 - SLIPPAGE)
        gross = qty * sell_px
        fee = gross * FEE_RATE
        net = gross - fee
        pnl = net - qty * entry

        trade_pnls.append(pnl)
        trade_returns.append(pnl / (qty * entry) if qty * entry else 0.0)

        cash += net
        qty = 0.0

        if with_curve and equity:
            equity[-1] = (df["ts"].iloc[-1], cash)

    wins = sum(1 for x in trade_pnls if x > 0)
    losses = sum(1 for x in trade_pnls if x < 0)
    gross_profit = float(sum(x for x in trade_pnls if x > 0))
    gross_loss = float(abs(sum(x for x in trade_pnls if x < 0)))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = float(np.mean(trade_pnls)) if trade_pnls else 0.0
    exposure = in_pos_bars / total_bars if total_bars else 0.0

    bpy = bars_per_year_for_df(df)
    eq_vals = [x[1] for x in equity] if with_curve else equity
    net_return, cagr, max_dd, sharpe, sortino, exposure = perf_stats(eq_vals, trade_returns, exposure, bpy)
    win_rate = wins / len(trade_pnls) if trade_pnls else 0.0

    score = (cagr * (1 + max(sharpe, 0))) / (1 + abs(max_dd)) if max_dd < 0 else cagr

    result = {
        "trades": len(trade_pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "net_return": net_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "sortino": sortino,
        "exposure": exposure,
        "score": score,
    }

    if with_curve:
        curve = pd.DataFrame(equity, columns=["ts", "equity"])
        curve["peak"] = curve["equity"].cummax()
        curve["drawdown"] = curve["equity"] / curve["peak"] - 1.0
        result["curve"] = curve

    return result


def grid_for_timeframe(tf: str):
    if tf == "4h":
        return [
            ("SmaCrossRegime", 8, 21, 80),
            ("SmaCrossRegime", 10, 30, 100),
            ("SmaCrossRegime", 12, 36, 120),
        ]
    return [
        ("SmaCrossRegime", 8, 21, 100),
        ("SmaCrossRegime", 12, 34, 144),
        ("SmaCrossRegime", 15, 45, 200),
    ]


def run():
    rows = []

    for asset, tf in product(ASSETS, TIMEFRAMES):
        try:
            df = fetch_ohlcv(asset, tf)
            if len(df) < 300:
                raise ValueError("not enough data")
        except Exception as e:
            rows.append({"asset": asset, "timeframe": tf, "error": str(e)})
            continue

        for strat, fast, slow, regime in grid_for_timeframe(tf):
            try:
                res = backtest(df, fast, slow, regime)

                print(
                    f"[GRID] {asset} {tf} "
                    f"fast={fast} slow={slow} regime={regime} "
                    f"trades={res['trades']} pf={res['profit_factor']:.4f} "
                    f"ret={res['net_return']:.4f}"
                )

                rows.append(asdict(BacktestResult(
                    asset=asset,
                    timeframe=tf,
                    strategy=strat,
                    fast=fast,
                    slow=slow,
                    regime=regime,
                    trades=res["trades"],
                    wins=res["wins"],
                    losses=res["losses"],
                    win_rate=res["win_rate"],
                    gross_profit=res["gross_profit"],
                    gross_loss=res["gross_loss"],
                    profit_factor=res["profit_factor"],
                    expectancy=res["expectancy"],
                    net_return=res["net_return"],
                    cagr=res["cagr"],
                    max_drawdown=res["max_drawdown"],
                    sharpe=res["sharpe"],
                    sortino=res["sortino"],
                    exposure=res["exposure"],
                    score=res["score"],
                )))
            except Exception as e:
                rows.append({
                    "asset": asset,
                    "timeframe": tf,
                    "strategy": strat,
                    "fast": fast,
                    "slow": slow,
                    "regime": regime,
                    "error": str(e),
                })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "research_results.csv", index=False)
    (OUT / "research_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    ok = df.copy()
    if "error" in ok.columns:
        ok = ok[ok["error"].isna()].copy()

    if len(ok):
        ok = ok.sort_values(
            ["timeframe", "score", "sharpe", "profit_factor"],
            ascending=[True, False, False, False],
        )
        ok.head(20).to_csv(OUT / "research_shortlist.csv", index=False)

    return df


def walk_forward_windows(df: pd.DataFrame, timeframe: str):
    n = len(df)

    if timeframe == "4h":
        candidates = [
            (365 * 6, 90 * 6),
            (180 * 6, 45 * 6),
            (120 * 6, 30 * 6),
            (90 * 6, 30 * 6),
            (60 * 6, 20 * 6),
        ]
    else:
        candidates = [
            (90 * 24, 30 * 24),
            (60 * 24, 20 * 24),
            (45 * 24, 14 * 24),
            (30 * 24, 10 * 24),
        ]

    for train_bars, test_bars in candidates:
        step_bars = test_bars
        if n < train_bars + test_bars:
            continue

        windows = []
        start = 0
        while start + train_bars + test_bars <= n:
            windows.append((start, start + train_bars, start + train_bars + test_bars))
            start += step_bars

        if len(windows) >= 3:
            print(
                f"[WFA] using rolling windows: "
                f"train={train_bars}, test={test_bars}, step={step_bars}, count={len(windows)}"
            )
            return windows

    if timeframe == "4h":
        train_bars = max(int(n * 0.50), 60 * 6)
        test_bars = max(int(n * 0.15), 20 * 6)
    else:
        train_bars = max(int(n * 0.50), 30 * 24)
        test_bars = max(int(n * 0.15), 10 * 24)

    if n < train_bars + test_bars:
        raise ValueError(
            f"not enough data even for fallback WFA: bars={n}, "
            f"required={train_bars + test_bars}"
        )

    windows = []
    train_end = train_bars
    while train_end + test_bars <= n:
        windows.append((0, train_end, train_end + test_bars))
        train_end += test_bars

    if len(windows) < 2:
        raise ValueError(
            f"too few windows for meaningful WFA: bars={n}, "
            f"train={train_bars}, test={test_bars}, count={len(windows)}"
        )

    print(
        f"[WFA] using expanding-window fallback: "
        f"train_start={train_bars}, test={test_bars}, count={len(windows)}"
    )
    return windows


def run_walk_forward_for_asset(asset: str = "BTCUSDT", timeframe: str = "4h"):
    df = fetch_ohlcv(asset, timeframe, limit=4000)

    print(f"[WFA] {asset} {timeframe} bars: {len(df)}")
    print(f"[WFA] start: {df['ts'].iloc[0]}  end: {df['ts'].iloc[-1]}")

    params = grid_for_timeframe(timeframe)
    windows = walk_forward_windows(df, timeframe)

    print(f"[WFA] windows generated: {len(windows)}")

    window_rows = []
    curve_parts = []

    for idx, (a, b, c) in enumerate(windows, start=1):
        train = df.iloc[a:b].copy()
        test = df.iloc[b:c].copy()

        best_param = None
        best_score = -1e18

        for strat, fast, slow, regime in params:
            train_res = backtest(train, fast, slow, regime)
            if train_res["score"] > best_score:
                best_score = train_res["score"]
                best_param = (strat, fast, slow, regime, train_res)

        strat, fast, slow, regime, train_res = best_param
        test_res = backtest(test, fast, slow, regime, with_curve=True)

        print(
            f"[WFA][window {idx}] "
            f"fast={fast} slow={slow} regime={regime} "
            f"trades={test_res['trades']} "
            f"ret={test_res['net_return']:.4f} "
            f"sharpe={test_res['sharpe']:.4f}"
        )

        curve = test_res["curve"].copy()
        curve["window"] = idx
        curve_parts.append(curve)

        window_rows.append({
            "window": idx,
            "asset": asset,
            "timeframe": timeframe,
            "strategy": strat,
            "fast": fast,
            "slow": slow,
            "regime": regime,
            "train_start": str(train["ts"].iloc[0]),
            "train_end": str(train["ts"].iloc[-1]),
            "test_start": str(test["ts"].iloc[0]),
            "test_end": str(test["ts"].iloc[-1]),
            "train_score": train_res["score"],
            "train_sharpe": train_res["sharpe"],
            "train_pf": train_res["profit_factor"],
            "train_return": train_res["net_return"],
            "test_trades": test_res["trades"],
            "test_win_rate": test_res["win_rate"],
            "test_profit_factor": test_res["profit_factor"],
            "test_expectancy": test_res["expectancy"],
            "test_net_return": test_res["net_return"],
            "test_cagr": test_res["cagr"],
            "test_max_drawdown": test_res["max_drawdown"],
            "test_sharpe": test_res["sharpe"],
            "test_sortino": test_res["sortino"],
            "test_exposure": test_res["exposure"],
            "test_score": test_res["score"],
        })

    wf = pd.DataFrame(window_rows)
    curve = pd.concat(curve_parts, ignore_index=True)

    summary = pd.DataFrame([{
        "asset": asset,
        "timeframe": timeframe,
        "windows": len(wf),
        "avg_test_return": wf["test_net_return"].mean(),
        "median_test_return": wf["test_net_return"].median(),
        "avg_test_sharpe": wf["test_sharpe"].mean(),
        "avg_test_pf": wf["test_profit_factor"].mean(),
        "worst_test_dd": wf["test_max_drawdown"].min(),
        "avg_test_score": wf["test_score"].mean(),
        "positive_windows": int((wf["test_net_return"] > 0).sum()),
        "total_oos_trades": int(wf["test_trades"].sum()),
        "avg_oos_trades_per_window": float(wf["test_trades"].mean()),
        "positive_window_ratio": float((wf["test_net_return"] > 0).mean()),
    }])

    wf.to_csv(OUT / "walkforward_windows.csv", index=False)
    summary.to_csv(OUT / "walkforward_summary.csv", index=False)
    curve.to_csv(OUT / "walkforward_equity_curve.csv", index=False)
    curve[["ts", "window", "drawdown"]].to_csv(OUT / "walkforward_drawdown_curve.csv", index=False)

    fig1 = px.line(curve, x="ts", y="equity", color="window", title="WFA equity curve (OOS)")
    fig1.update_layout(
        title={
            "text": "WFA equity curve (OOS)<br><span style='font-size: 18px; font-weight: normal;'>Source: Binance/yfinance | out-of-sample by window</span>"
        }
    )
    fig1.update_xaxes(title_text="Time")
    fig1.update_yaxes(title_text="Equity")
    fig1.write_image(OUT / "walkforward_equity_curve.png")
    (OUT / "walkforward_equity_curve.png.meta.json").write_text(
        json.dumps({
            "caption": "Walk-forward equity curve",
            "description": "Out-of-sample equity curve by walk-forward test window."
        }),
        encoding="utf-8",
    )

    fig2 = px.line(curve, x="ts", y="drawdown", color="window", title="WFA drawdown (OOS)")
    fig2.update_layout(
        title={
            "text": "WFA drawdown (OOS)<br><span style='font-size: 18px; font-weight: normal;'>Source: Binance/yfinance | out-of-sample drawdown by window</span>"
        }
    )
    fig2.update_xaxes(title_text="Time")
    fig2.update_yaxes(title_text="Drawdown")
    fig2.write_image(OUT / "walkforward_drawdown_curve.png")
    (OUT / "walkforward_drawdown_curve.png.meta.json").write_text(
        json.dumps({
            "caption": "Walk-forward drawdown curve",
            "description": "Out-of-sample drawdown curve by walk-forward test window."
        }),
        encoding="utf-8",
    )

    metrics = summary.melt(
        id_vars=["asset", "timeframe", "windows", "positive_windows"],
        value_vars=[
            "avg_test_return",
            "median_test_return",
            "avg_test_sharpe",
            "avg_test_pf",
            "worst_test_dd",
            "avg_test_score",
            "total_oos_trades",
            "avg_oos_trades_per_window",
            "positive_window_ratio",
        ],
        var_name="metric",
        value_name="value",
    )

    fig3 = px.bar(metrics, x="metric", y="value", title="WFA summary metrics")
    fig3.update_traces(cliponaxis=False)
    fig3.update_layout(
        title={
            "text": "WFA summary metrics<br><span style='font-size: 18px; font-weight: normal;'>Source: Binance/yfinance | aggregate OOS metrics</span>"
        }
    )
    fig3.update_xaxes(title_text="Metric")
    fig3.update_yaxes(title_text="Value")
    fig3.write_image(OUT / "walkforward_metrics.png")
    (OUT / "walkforward_metrics.png.meta.json").write_text(
        json.dumps({
            "caption": "Walk-forward summary metrics",
            "description": "Aggregate out-of-sample performance metrics from walk-forward analysis."
        }),
        encoding="utf-8",
    )

    return wf, summary, curve


if __name__ == "__main__":
    results = run()
    print("Research results saved:", len(results))

    try:
        wf, summary, curve = run_walk_forward_for_asset("BTCUSDT", "4h")
        print(summary.to_string(index=False))
    except Exception as e:
        print(f"WFA skipped: {e}")