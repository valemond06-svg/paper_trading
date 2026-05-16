import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("output")
OUT.mkdir(exist_ok=True)

RESEARCH_RESULTS = OUT / "research_results.csv"
WFA_SUMMARY = OUT / "walkforward_summary.csv"

RANKED_OUT = OUT / "strategy_ranked.csv"
SHORTLIST_OUT = OUT / "strategy_shortlist.csv"
REPORT_OUT = OUT / "strategy_rank_report.json"


def safe_num(x, default=0.0):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def normalize(series, higher_better=True):
    s = series.astype(float).copy()
    if s.nunique(dropna=True) <= 1:
        return pd.Series(np.ones(len(s)) * 0.5, index=s.index)

    lo = s.min()
    hi = s.max()
    if hi == lo:
        return pd.Series(np.ones(len(s)) * 0.5, index=s.index)

    norm = (s - lo) / (hi - lo)
    if not higher_better:
        norm = 1 - norm
    return norm.clip(0, 1)


def load_data():
    if not RESEARCH_RESULTS.exists():
        raise FileNotFoundError(f"Missing {RESEARCH_RESULTS}")
    research = pd.read_csv(RESEARCH_RESULTS)

    if WFA_SUMMARY.exists():
        wfa = pd.read_csv(WFA_SUMMARY)
    else:
        wfa = pd.DataFrame(columns=[
            "asset", "timeframe", "windows", "avg_test_return", "median_test_return",
            "avg_test_sharpe", "avg_test_pf", "worst_test_dd", "avg_test_score",
            "positive_windows", "total_oos_trades", "avg_oos_trades_per_window",
            "positive_window_ratio"
        ])

    return research, wfa


def build_ranked_table(research: pd.DataFrame, wfa: pd.DataFrame) -> pd.DataFrame:
    df = research.copy()

    if "error" in df.columns:
        df = df[df["error"].isna()].copy()

    for col in [
        "trades", "wins", "losses", "win_rate", "gross_profit", "gross_loss",
        "profit_factor", "expectancy", "net_return", "cagr", "max_drawdown",
        "sharpe", "sortino", "exposure", "score"
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    wfa_cols = [
        "asset", "timeframe", "windows", "avg_test_return", "median_test_return",
        "avg_test_sharpe", "avg_test_pf", "worst_test_dd", "avg_test_score",
        "positive_windows", "total_oos_trades", "avg_oos_trades_per_window",
        "positive_window_ratio"
    ]
    if len(wfa):
        for col in wfa.columns:
            if col not in wfa_cols and col in wfa.columns:
                wfa[col] = pd.to_numeric(wfa[col], errors="ignore")

    if len(wfa):
        df = df.merge(wfa, on=["asset", "timeframe"], how="left", suffixes=("", "_wfa"))
    else:
        for c in [
            "windows", "avg_test_return", "median_test_return", "avg_test_sharpe",
            "avg_test_pf", "worst_test_dd", "avg_test_score", "positive_windows",
            "total_oos_trades", "avg_oos_trades_per_window", "positive_window_ratio"
        ]:
            df[c] = np.nan

    df["trades"] = df["trades"].fillna(0)
    df["win_rate"] = df["win_rate"].fillna(0)
    df["profit_factor"] = df["profit_factor"].replace([np.inf, -np.inf], np.nan).fillna(0)
    df["expectancy"] = df["expectancy"].fillna(0)
    df["net_return"] = df["net_return"].fillna(0)
    df["cagr"] = df["cagr"].fillna(0)
    df["max_drawdown"] = df["max_drawdown"].fillna(0)
    df["sharpe"] = df["sharpe"].fillna(0)
    df["sortino"] = df["sortino"].fillna(0)
    df["score"] = df["score"].fillna(0)

    df["avg_test_return"] = df["avg_test_return"].fillna(0)
    df["avg_test_sharpe"] = df["avg_test_sharpe"].fillna(0)
    df["avg_test_pf"] = df["avg_test_pf"].replace([np.inf, -np.inf], np.nan).fillna(0)
    df["worst_test_dd"] = df["worst_test_dd"].fillna(0)
    df["avg_test_score"] = df["avg_test_score"].fillna(0)
    df["positive_window_ratio"] = df["positive_window_ratio"].fillna(0)
    df["total_oos_trades"] = df["total_oos_trades"].fillna(0)
    df["avg_oos_trades_per_window"] = df["avg_oos_trades_per_window"].fillna(0)
    df["windows"] = df["windows"].fillna(0)

    df["pf_norm"] = normalize(df["profit_factor"], higher_better=True)
    df["ret_norm"] = normalize(df["net_return"], higher_better=True)
    df["cagr_norm"] = normalize(df["cagr"], higher_better=True)
    df["sharpe_norm"] = normalize(df["sharpe"], higher_better=True)
    df["sortino_norm"] = normalize(df["sortino"], higher_better=True)
    df["dd_norm"] = normalize(df["max_drawdown"], higher_better=False)
    df["trades_norm"] = normalize(np.log1p(df["trades"]), higher_better=True)
    df["wfa_ret_norm"] = normalize(df["avg_test_return"], higher_better=True)
    df["wfa_sharpe_norm"] = normalize(df["avg_test_sharpe"], higher_better=True)
    df["wfa_pf_norm"] = normalize(df["avg_test_pf"], higher_better=True)
    df["wfa_dd_norm"] = normalize(df["worst_test_dd"], higher_better=False)
    df["wfa_score_norm"] = normalize(df["avg_test_score"], higher_better=True)
    df["wfa_ratio_norm"] = normalize(df["positive_window_ratio"], higher_better=True)
    df["wfa_trades_norm"] = normalize(np.log1p(df["total_oos_trades"]), higher_better=True)

    df["base_score"] = (
        0.18 * df["pf_norm"] +
        0.18 * df["ret_norm"] +
        0.12 * df["cagr_norm"] +
        0.12 * df["sharpe_norm"] +
        0.08 * df["sortino_norm"] +
        0.10 * df["dd_norm"] +
        0.12 * df["trades_norm"] +
        0.10 * df["score"].clip(lower=0)
    )

    df["wfa_score"] = (
        0.22 * df["wfa_pf_norm"] +
        0.18 * df["wfa_ret_norm"] +
        0.18 * df["wfa_sharpe_norm"] +
        0.10 * df["wfa_dd_norm"] +
        0.12 * df["wfa_score_norm"] +
        0.10 * df["wfa_ratio_norm"] +
        0.10 * df["wfa_trades_norm"]
    )

    df["consistency_bonus"] = 0.0
    df.loc[df["timeframe"].eq("1h"), "consistency_bonus"] += 0.02
    df.loc[df["timeframe"].eq("4h"), "consistency_bonus"] += 0.02

    df["final_score"] = (
        0.55 * df["base_score"] +
        0.40 * df["wfa_score"] +
        0.05 * df["consistency_bonus"]
    )

    df["final_score"] = df["final_score"].clip(0, 1)

    df = df.sort_values(
        ["final_score", "wfa_score", "base_score", "profit_factor", "sharpe"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    return df


def build_shortlist(df: pd.DataFrame) -> pd.DataFrame:
    shortlist = df.copy()

    shortlist = shortlist[
        (shortlist["trades"] >= 8) &
        (shortlist["profit_factor"] >= 1.0) &
        (shortlist["net_return"] >= 0.0)
    ].copy()

    if len(shortlist) == 0:
        shortlist = df[df["trades"] >= 5].copy()

    shortlist = shortlist.head(10).reset_index(drop=True)
    return shortlist


def make_report(df: pd.DataFrame, shortlist: pd.DataFrame):
    report = {
        "total_candidates": int(len(df)),
        "shortlist_size": int(len(shortlist)),
        "top_candidate": None,
        "timeframe_distribution": {},
        "asset_distribution": {},
        "notes": []
    }

    if len(df):
        top = df.iloc[0]
        report["top_candidate"] = {
            "asset": str(top["asset"]),
            "timeframe": str(top["timeframe"]),
            "strategy": str(top["strategy"]),
            "fast": int(top["fast"]),
            "slow": int(top["slow"]),
            "regime": int(top["regime"]),
            "final_score": safe_num(top["final_score"]),
            "profit_factor": safe_num(top["profit_factor"]),
            "net_return": safe_num(top["net_return"]),
            "max_drawdown": safe_num(top["max_drawdown"]),
            "sharpe": safe_num(top["sharpe"]),
            "avg_test_return": safe_num(top["avg_test_return"]),
            "positive_window_ratio": safe_num(top["positive_window_ratio"]),
        }

    if "timeframe" in df.columns:
        report["timeframe_distribution"] = df["timeframe"].value_counts(dropna=False).to_dict()

    if "asset" in df.columns:
        report["asset_distribution"] = df["asset"].value_counts(dropna=False).to_dict()

    if len(shortlist):
        report["notes"].append("Shortlist filtered to candidates with trades >= 8, PF >= 1.0 and non-negative net return.")
    else:
        report["notes"].append("No candidate met strict shortlist filters; fallback shortlist uses trades >= 5.")

    weak_wfa = df["positive_window_ratio"].fillna(0).mean() if len(df) else 0
    if weak_wfa < 0.5:
        report["notes"].append("Walk-forward consistency is weak on the current sample; treat results as exploratory.")

    return report


def main():
    research, wfa = load_data()
    ranked = build_ranked_table(research, wfa)
    shortlist = build_shortlist(ranked)
    report = make_report(ranked, shortlist)

    ranked.to_csv(RANKED_OUT, index=False)
    shortlist.to_csv(SHORTLIST_OUT, index=False)

    REPORT_OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Ranked candidates saved to: {RANKED_OUT}")
    print(f"Shortlist saved to: {SHORTLIST_OUT}")
    print(f"Report saved to: {REPORT_OUT}")
    if report["top_candidate"]:
        print("Top candidate:")
        print(json.dumps(report["top_candidate"], indent=2))
    print("\nShortlist preview:")
    cols = [
        "asset", "timeframe", "strategy", "fast", "slow", "regime",
        "final_score", "profit_factor", "net_return", "max_drawdown",
        "sharpe", "avg_test_return", "positive_window_ratio"
    ]
    available = [c for c in cols if c in shortlist.columns]
    if len(shortlist):
        print(shortlist[available].to_string(index=False))


if __name__ == "__main__":
    main()