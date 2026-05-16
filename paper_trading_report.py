import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path("output")
OUT.mkdir(exist_ok=True)

RANKED_CSV = OUT / "strategy_ranked.csv"
SHORTLIST_CSV = OUT / "strategy_shortlist.csv"
ALLOC_CSV = OUT / "portfolio_allocation.csv"
PLAN_JSON = OUT / "paper_trading_plan.json"

REPORT_TXT = OUT / "paper_trading_report.txt"
REPORT_JSON = OUT / "paper_trading_report.json"


def load_csv(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return pd.read_csv(path)


def fmt_pct(x):
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "n/a"


def fmt_num(x, digits=4):
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "n/a"


def safe_row_value(row, key, default="n/a"):
    try:
        v = row.get(key, default)
        if pd.isna(v):
            return default
        return v
    except Exception:
        return default


def build_report():
    ranked = load_csv(RANKED_CSV)
    shortlist = load_csv(SHORTLIST_CSV)
    alloc = load_csv(ALLOC_CSV)

    top = ranked.iloc[0] if len(ranked) else None
    ts = datetime.now(timezone.utc).isoformat()

    report = {
        "generated_at_utc": ts,
        "summary": {
            "ranked_candidates": int(len(ranked)),
            "shortlist_candidates": int(len(shortlist)),
            "allocated_candidates": int(len(alloc)),
        },
        "top_candidate": None,
        "shortlist": [],
        "allocation": [],
        "risk_rules": {
            "base_risk_per_trade": "0.25% to 1.0%",
            "max_portfolio_risk": "3.0%",
            "dd_3pct": "Reduce all weights by 20%",
            "dd_5pct": "Reduce all weights by 40%",
            "dd_7pct": "Pause new entries and review",
            "review_trigger": "Any strategy with 3 consecutive negative windows or weekly equity deterioration",
        },
        "next_actions": [
            "Run paper trading only on selected allocation basket",
            "Log every trade with strategy id and window context",
            "Review results weekly against walk-forward expectations",
            "Remove or downsize any strategy that falls below PF 1.0 over a rolling month",
        ],
    }

    if top is not None:
        report["top_candidate"] = {
            "asset": safe_row_value(top, "asset"),
            "timeframe": safe_row_value(top, "timeframe"),
            "strategy": safe_row_value(top, "strategy"),
            "fast": int(safe_row_value(top, "fast", 0)),
            "slow": int(safe_row_value(top, "slow", 0)),
            "regime": int(safe_row_value(top, "regime", 0)),
            "final_score": float(safe_row_value(top, "final_score", 0.0)),
            "profit_factor": float(safe_row_value(top, "profit_factor", 0.0)),
            "net_return": float(safe_row_value(top, "net_return", 0.0)),
            "max_drawdown": float(safe_row_value(top, "max_drawdown", 0.0)),
            "sharpe": float(safe_row_value(top, "sharpe", 0.0)),
            "avg_test_return": float(safe_row_value(top, "avg_test_return", 0.0)),
            "positive_window_ratio": float(safe_row_value(top, "positive_window_ratio", 0.0)),
        }

    shortlist_cols = [c for c in [
        "asset", "timeframe", "strategy", "fast", "slow", "regime",
        "final_score", "profit_factor", "net_return", "max_drawdown",
        "sharpe", "avg_test_return", "positive_window_ratio", "trades"
    ] if c in shortlist.columns]

    alloc_cols = [c for c in [
        "asset", "timeframe", "strategy", "fast", "slow", "regime",
        "target_weight", "risk_per_trade", "allocation_score", "profit_factor",
        "net_return", "max_drawdown", "sharpe"
    ] if c in alloc.columns]

    report["shortlist"] = shortlist[shortlist_cols].to_dict(orient="records") if len(shortlist) else []
    report["allocation"] = alloc[alloc_cols].to_dict(orient="records") if len(alloc) else []

    lines = []
    lines.append("PAPER TRADING REPORT")
    lines.append("=" * 80)
    lines.append(f"Generated at UTC: {ts}")
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 80)
    lines.append(f"Ranked candidates: {len(ranked)}")
    lines.append(f"Shortlist candidates: {len(shortlist)}")
    lines.append(f"Allocated candidates: {len(alloc)}")
    lines.append("")

    if report["top_candidate"]:
        topc = report["top_candidate"]
        lines.append("TOP CANDIDATE")
        lines.append("-" * 80)
        lines.append(
            f'{topc["asset"]} {topc["timeframe"]} {topc["strategy"]} '
            f'({topc["fast"]}/{topc["slow"]}/{topc["regime"]})'
        )
        lines.append(f'Final score: {fmt_num(topc["final_score"], 4)}')
        lines.append(f'Profit factor: {fmt_num(topc["profit_factor"], 4)}')
        lines.append(f'Net return: {fmt_pct(topc["net_return"])}')
        lines.append(f'Max drawdown: {fmt_pct(topc["max_drawdown"])}')
        lines.append(f'Sharpe: {fmt_num(topc["sharpe"], 2)}')
        lines.append(f'Avg test return: {fmt_pct(topc["avg_test_return"])}')
        lines.append(f'Positive window ratio: {fmt_pct(topc["positive_window_ratio"])}')
        lines.append("")

    lines.append("ALLOCATION")
    lines.append("-" * 80)
    for row in alloc.to_dict(orient="records"):
        lines.append(
            f'{row.get("asset")} {row.get("timeframe")} '
            f'w={fmt_pct(row.get("target_weight", 0))} '
            f'risk={fmt_pct(row.get("risk_per_trade", 0))} '
            f'PF={fmt_num(row.get("profit_factor", 0), 2)} '
            f'ret={fmt_pct(row.get("net_return", 0))}'
        )
    lines.append("")

    lines.append("RISK RULES")
    lines.append("-" * 80)
    for k, v in report["risk_rules"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("NEXT ACTIONS")
    lines.append("-" * 80)
    for a in report["next_actions"]:
        lines.append(f"- {a}")

    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Report saved to: {REPORT_TXT}")
    print(f"JSON saved to: {REPORT_JSON}")
    print("")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    build_report()