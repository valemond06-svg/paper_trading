import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("output")
OUT.mkdir(exist_ok=True)

SHORTLIST_CSV = OUT / "strategy_shortlist.csv"
ALLOC_OUT = OUT / "portfolio_allocation.csv"
PLAN_OUT = OUT / "paper_trading_plan.json"


def safe_float(x, default=0.0):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def load_shortlist():
    if not SHORTLIST_CSV.exists():
        raise FileNotFoundError(f"Missing {SHORTLIST_CSV}")
    df = pd.read_csv(SHORTLIST_CSV)
    return df


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score_row(row):
    final_score = safe_float(row.get("final_score", 0.0))
    pf = safe_float(row.get("profit_factor", 0.0))
    net_return = safe_float(row.get("net_return", 0.0))
    sharpe = safe_float(row.get("sharpe", 0.0))
    drawdown = abs(safe_float(row.get("max_drawdown", 0.0)))
    wfa_ratio = safe_float(row.get("positive_window_ratio", 0.0))
    avg_test_ret = safe_float(row.get("avg_test_return", 0.0))

    base = (
        0.40 * final_score +
        0.18 * clamp((pf - 1.0) / 1.0) +
        0.12 * clamp(net_return / 0.05) +
        0.10 * clamp(sharpe / 20.0) +
        0.10 * clamp(avg_test_ret / 0.02) +
        0.10 * clamp(wfa_ratio)
    )

    dd_penalty = clamp(drawdown / 0.05)
    score = base * (1.0 - 0.35 * dd_penalty)

    return clamp(score)


def build_allocation(df):
    if len(df) == 0:
        raise ValueError("Empty shortlist")

    work = df.copy()
    work["allocation_score"] = work.apply(score_row, axis=1)

    work = work.sort_values(
        ["allocation_score", "final_score", "profit_factor", "sharpe"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    top_n = min(3, len(work))
    selected = work.head(top_n).copy()

    raw_weights = []
    for _, row in selected.iterrows():
        s = safe_float(row["allocation_score"], 0.0)
        pf = safe_float(row.get("profit_factor", 0.0), 0.0)
        dd = abs(safe_float(row.get("max_drawdown", 0.0), 0.0))
        trades = safe_float(row.get("trades", 0.0), 0.0)

        weight = s
        weight *= 1.0 + clamp((pf - 1.0) / 1.5, 0.0, 0.35)
        weight *= 1.0 - clamp(dd / 0.08, 0.0, 0.40)
        weight *= 1.0 + clamp(np.log1p(trades) / 5.0, 0.0, 0.20)
        raw_weights.append(max(weight, 0.0))

    raw_weights = np.array(raw_weights, dtype=float)
    if raw_weights.sum() <= 0:
        raw_weights = np.ones(len(selected), dtype=float)

    weights = raw_weights / raw_weights.sum()

    selected["target_weight"] = weights
    selected["risk_per_trade"] = selected["target_weight"].apply(lambda w: round(0.01 * clamp(w / 0.5, 0.4, 1.0), 4))
    selected["max_concurrent"] = selected["timeframe"].map(lambda tf: 1 if tf == "4h" else 2)
    selected["enabled"] = True

    cols = [
        "asset", "timeframe", "strategy", "fast", "slow", "regime",
        "final_score", "allocation_score", "target_weight",
        "risk_per_trade", "max_concurrent", "profit_factor",
        "net_return", "max_drawdown", "sharpe", "avg_test_return",
        "positive_window_ratio", "trades"
    ]
    available = [c for c in cols if c in selected.columns]

    selected[available].to_csv(ALLOC_OUT, index=False)

    plan = {
        "total_candidates": int(len(df)),
        "selected_candidates": int(len(selected)),
        "allocation_mode": "score_weighted_risk_adjusted",
        "base_risk_per_trade": 0.01,
        "max_portfolio_risk": 0.03,
        "rebalance_frequency": "daily",
        "drawdown_rules": {
            "dd_3pct": "reduce all weights by 20%",
            "dd_5pct": "reduce all weights by 40%",
            "dd_7pct": "pause new entries and review",
        },
        "selected": selected[available].to_dict(orient="records"),
    }

    PLAN_OUT.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    return selected


def main():
    df = load_shortlist()
    alloc = build_allocation(df)

    print(f"Allocation saved to: {ALLOC_OUT}")
    print(f"Plan saved to: {PLAN_OUT}")
    print("\nAllocation preview:")
    cols = [
        "asset", "timeframe", "strategy", "fast", "slow", "regime",
        "target_weight", "risk_per_trade", "allocation_score",
        "profit_factor", "net_return", "max_drawdown", "sharpe"
    ]
    cols = [c for c in cols if c in alloc.columns]
    print(alloc[cols].to_string(index=False))


if __name__ == "__main__":
    main()