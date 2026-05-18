#!/usr/bin/env python3
"""
adx_experiment.py – Esperimento ADX Filter su SMA Crossover 4h
Autore: Valentino Mondini | Generato con Perplexity AI
Repo: https://github.com/valemond06-svg/paper_trading

FASE A: Baseline 4h (ExitA e ExitB)
FASE B: SMA Crossover + ADX filter (soglie 20, 25, 30)
FASE C: Metriche complete OOS 2 anni
FASE D: Output JSON, CSV, PNG

Uso:
    python adx_experiment.py
    # Richiede: data/4h/BTCUSDT.csv, data/4h/ETHUSDT.csv
"""
import json, math, os
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── CONFIG ────────────────────────────────────────────────────────────────────
DATA_DIR   = Path("data/4h")
OUT        = Path("output"); OUT.mkdir(exist_ok=True)
FAST, SLOW = 12, 34
FEE_RATE   = 0.001
SLIPPAGE   = 0.0005
INIT_CAP   = 1000.0
ALLOC      = 0.25
MIN_TRADE  = 5.0
ATR_PERIOD = 14
ADX_PERIOD = 14
BPY        = 365 * 6       # barre/anno su 4h (6 candele * 365 giorni)
TRAIN_BARS = int(365*6*4)  # ~4 anni warmup/train
TEST_BARS  = int(365*6*2)  # ~2 anni OOS
ASSETS     = ["BTCUSDT", "ETHUSDT"]
ADX_THRESHOLDS = [None, 20, 25, 30]  # None = baseline senza filtro

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_csv(asset: str) -> pd.DataFrame:
    p = DATA_DIR / f"{asset}.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing: {p}. Metti il CSV in data/4h/{asset}.csv")
    df = pd.read_csv(p)
    df.columns = [c.lower() for c in df.columns]
    ts_col = next((c for c in df.columns if "time" in c or c in ["ts", "date", "datetime"]), None)
    if ts_col and ts_col != "ts":
        df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["ts", "close"]).sort_values("ts").reset_index(drop=True)

# ── INDICATORI ────────────────────────────────────────────────────────────────
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ADX(n) con smoothing Wilder (rolling sum approssimato)."""
    h, l, c = df["high"], df["low"], df["close"]
    plus_dm  = (h - h.shift(1)).clip(lower=0)
    minus_dm = (l.shift(1) - l).clip(lower=0)
    cond = plus_dm >= minus_dm
    plus_dm  = plus_dm.where(cond, 0.0)
    minus_dm = minus_dm.where(~cond, 0.0)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr_w = tr.rolling(n).sum()
    pdm_w = plus_dm.rolling(n).sum()
    mdm_w = minus_dm.rolling(n).sum()
    pdi = 100 * pdm_w / atr_w.replace(0, np.nan)
    mdi = 100 * mdm_w / atr_w.replace(0, np.nan)
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.rolling(n).mean().fillna(0)

def crossover_signals(df: pd.DataFrame):
    """True crossover: entry solo fronte 0→1, exit solo fronte 1→0."""
    bull = (sma(df["close"], FAST) > sma(df["close"], SLOW)).astype(int)
    diff = bull - bull.shift(1).fillna(0)
    return (diff == 1), (diff == -1)

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def backtest(df: pd.DataFrame, exit_type: str = "A", adx_threshold=None):
    """
    exit_type: 'A' = SL 2% / TP 3% fisso
               'B' = SL ATR(14)*1.5 / TP ATR(14)*2.5
    adx_threshold: None = nessun filtro, int = ADX > soglia richiesto per entry
    """
    entry_s, exit_s = crossover_signals(df)
    atr_s = calc_atr(df, ATR_PERIOD)
    adx_s = calc_adx(df, ADX_PERIOD)

    cash, qty, entry_px = INIT_CAP, 0.0, 0.0
    equity, pnls, hold_bars, entry_bar = [], [], [], 0
    stop_px = tp_px = 0.0
    total_fees = 0.0

    for i in range(len(df)):
        px = float(df["close"].iloc[i])
        eq = cash + qty * px
        equity.append(eq)

        # SL/TP check
        if qty > 0 and (px <= stop_px or px >= tp_px):
            sp = px * (1 - SLIPPAGE)
            gross = qty * sp
            fee = gross * FEE_RATE
            total_fees += fee
            pnls.append(gross - fee - qty * entry_px)
            hold_bars.append(i - entry_bar)
            cash += gross - fee
            qty = 0.0; entry_px = 0.0

        # Entry
        if entry_s.iloc[i] and qty == 0 and cash > MIN_TRADE:
            adx_ok = True if adx_threshold is None else float(adx_s.iloc[i]) > adx_threshold
            if adx_ok:
                spend = min(eq * ALLOC, cash)
                if spend >= MIN_TRADE:
                    bp = px * (1 + SLIPPAGE)
                    fee = spend * FEE_RATE
                    total_fees += fee
                    qty = (spend - fee) / bp
                    cash -= spend
                    entry_px = bp
                    entry_bar = i
                    av = float(atr_s.iloc[i])
                    if exit_type == "A" or av <= 0:
                        stop_px = entry_px * 0.98
                        tp_px   = entry_px * 1.03
                    else:
                        stop_px = entry_px - 1.5 * av
                        tp_px   = entry_px + 2.5 * av

        # Exit crossover reversal
        elif exit_s.iloc[i] and qty > 0:
            sp = px * (1 - SLIPPAGE)
            gross = qty * sp
            fee = gross * FEE_RATE
            total_fees += fee
            pnls.append(gross - fee - qty * entry_px)
            hold_bars.append(i - entry_bar)
            cash += gross - fee
            qty = 0.0; entry_px = 0.0

    # Close final position
    if qty > 0:
        sp = float(df["close"].iloc[-1]) * (1 - SLIPPAGE)
        gross = qty * sp; fee = gross * FEE_RATE; total_fees += fee
        pnls.append(gross - fee - qty * entry_px)
        hold_bars.append(len(df) - 1 - entry_bar)
        cash += gross - fee

    return np.array(equity), pnls, hold_bars, total_fees

# ── METRICHE ──────────────────────────────────────────────────────────────────
def compute_metrics(eq_arr, pnls, hold_bars, total_fees, label, asset):
    eq = pd.Series(eq_arr)
    ret  = float(eq.iloc[-1] / eq.iloc[0] - 1)
    yrs  = len(eq) / BPY
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else 0
    dd   = float((eq / eq.cummax() - 1).min())
    br   = eq.pct_change().dropna()
    mu, std = br.mean(), br.std(ddof=0)
    neg  = br[br < 0]; down = neg.std(ddof=0) if len(neg) > 1 else 1e-9
    sharpe  = float(mu / std  * math.sqrt(BPY)) if std  > 1e-10 else 0.0
    sortino = float(mu / down * math.sqrt(BPY)) if down > 1e-10 else 0.0
    wins = [x for x in pnls if x > 0]
    loss = [x for x in pnls if x <= 0]
    gp = sum(wins); gl = abs(sum(loss))
    pf  = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0.0)
    wr  = len(wins) / len(pnls) if pnls else 0.0
    exp_val   = float(np.mean(pnls)) if pnls else 0.0
    avg_hold  = float(np.mean(hold_bars)) if hold_bars else 0.0
    trades_yr = len(pnls) / yrs if yrs > 0 else 0

    # Decisione deploy (almeno 2 su 3 soglie soddisfatte)
    ok = sum([sharpe > 1.0, pf > 1.3, dd > -0.20])
    if ok >= 2:
        verdict = "PROMETTENTE"
    elif ok == 1:
        verdict = "INTERESSANTE MA INSUFFICIENTE"
    else:
        verdict = "INSUFFICIENTE"

    return dict(
        label=label, asset=asset,
        total_return_pct=round(ret * 100, 2),
        cagr_pct=round(cagr * 100, 2),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        max_drawdown_pct=round(dd * 100, 2),
        profit_factor=round(pf, 3),
        win_rate_pct=round(wr * 100, 2),
        expectancy_usd=round(exp_val, 4),
        n_trades=len(pnls),
        trades_per_year=round(trades_yr, 1),
        avg_hold_h=round(avg_hold * 4, 1),
        fee_cumulative_usd=round(total_fees, 2),
        sharpe_ok=sharpe > 1.0,
        pf_ok=pf > 1.3,
        dd_ok=dd > -0.20,
        verdict=verdict
    )

# ── CHART BUILDER ─────────────────────────────────────────────────────────────
def build_charts(all_results, all_curves):
    df_out = pd.DataFrame(all_results)
    btc_r = df_out[df_out.asset == "BTCUSDT"]
    eth_r = df_out[df_out.asset == "ETHUSDT"]
    short_labels = ["Base", "ADX20", "ADX25", "ADX30"]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            "BTC – Equity Curves (Norm 100, ExitB)",
            "ETH – Equity Curves (Norm 100, ExitB)",
            "Sharpe Ratio – ExitB (soglia Sharpe=1.0)",
            "Profit Factor – ExitB (soglia PF=1.3)"
        ],
        vertical_spacing=0.18, horizontal_spacing=0.12
    )

    btc_style = {
        "Baseline": ("#e74c3c", "solid"),
        "ADX20":    ("#f1c40f", "dot"),
        "ADX25":    ("#f39c12", "dash"),
        "ADX30":    ("#e67e22", "dashdot")
    }
    eth_style = {
        "Baseline": ("#3498db", "solid"),
        "ADX20":    ("#9b59b6", "dot"),
        "ADX25":    ("#2ecc71", "dash"),
        "ADX30":    ("#1abc9c", "dashdot")
    }

    for asset, style, row, col in [
        ("BTCUSDT", btc_style, 1, 1),
        ("ETHUSDT", eth_style, 1, 2)
    ]:
        for thr_lbl, (color, dash) in style.items():
            key = f"{asset}_{thr_lbl}_ExitB"
            if key in all_curves:
                ts, eq = all_curves[key]
                eq_n = eq / eq[0] * 100
                fig.add_trace(go.Scatter(
                    x=ts, y=eq_n, name=thr_lbl,
                    line=dict(color=color, width=2, dash=dash),
                    showlegend=(col == 1)
                ), row=row, col=col)

    btc_b = btc_r[btc_r.label.str.contains("ExitB")]
    eth_b = eth_r[eth_r.label.str.contains("ExitB")]
    for col_val, nm, rdf in [("#e74c3c", "BTC", btc_b), ("#3498db", "ETH", eth_b)]:
        fig.add_trace(go.Bar(
            x=short_labels, y=rdf.sharpe.tolist(), name=nm,
            marker_color=col_val, showlegend=False
        ), row=2, col=1)
        fig.add_trace(go.Bar(
            x=short_labels, y=rdf.profit_factor.tolist(), name=nm,
            marker_color=col_val, showlegend=False
        ), row=2, col=2)

    fig.add_hline(y=1.0, line_dash="dash", line_color="yellow", opacity=0.8, row=2, col=1)
    fig.add_hline(y=1.3, line_dash="dash", line_color="yellow", opacity=0.8, row=2, col=2)
    fig.update_layout(
        title={"text": (
            "4h SMA Crossover + ADX Filter – OOS 2y Dashboard<br>"
            "<span style='font-size:14px;font-weight:normal'>"
            "BTC & ETH | Fee 0.1% | Slip 0.05% | ExitB = ATR(14)×1.5 SL / ×2.5 TP"
            "</span>"
        )},
        legend=dict(orientation="h", yanchor="bottom", y=-0.08, xanchor="center", x=0.5),
        barmode="group",
        font=dict(size=12),
        height=800
    )
    fig.update_yaxes(title_text="Equity (100)", row=1, col=1)
    fig.update_yaxes(title_text="Equity (100)", row=1, col=2)
    fig.update_yaxes(title_text="Sharpe", row=2, col=1)
    fig.update_yaxes(title_text="Profit Factor", row=2, col=2)
    fig.write_image(str(OUT / "4h_adx_equity_curves.png"))

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_results = []
    all_curves  = {}

    for asset in ASSETS:
        df_full = load_csv(asset)
        total = len(df_full)
        tb = TRAIN_BARS if total >= TRAIN_BARS + TEST_BARS else int(total * 4 / 6)
        te = TEST_BARS  if total >= TRAIN_BARS + TEST_BARS else total - tb
        test = df_full.iloc[tb:tb+te].reset_index(drop=True)

        print(f"\n[{asset}] OOS: {test['ts'].iloc[0].date()} → {test['ts'].iloc[-1].date()} "
              f"({len(test)} barre)")

        for adx_thr in ADX_THRESHOLDS:
            for exit_type in ["A", "B"]:
                prefix = "Baseline" if adx_thr is None else f"ADX{adx_thr}"
                label  = f"{prefix}_Exit{exit_type}"
                eq, pnls, hold_bars, fees = backtest(test, exit_type=exit_type,
                                                     adx_threshold=adx_thr)
                m = compute_metrics(eq, pnls, hold_bars, fees, label, asset)
                all_results.append(m)
                all_curves[f"{asset}_{label}"] = (test["ts"].values, eq)

                print(f"  {label:22s}: ret={m['total_return_pct']:6.1f}%  "
                      f"sharpe={m['sharpe']:5.3f}  pf={m['profit_factor']:5.3f}  "
                      f"dd={m['max_drawdown_pct']:6.1f}%  trades={m['n_trades']:3d}  "
                      f"→ {m['verdict']}")

    # Save outputs
    df_out = pd.DataFrame(all_results)
    df_out.to_csv(OUT / "4h_adx_experiment.csv", index=False)
    (OUT / "4h_adx_experiment.json").write_text(
        json.dumps(all_results, indent=2, default=str)
    )
    build_charts(all_results, all_curves)

    # Print summary table
    print("\n" + "=" * 108)
    print("TABELLA RIEPILOGATIVA – 4h SMA CROSSOVER + ADX FILTER | OOS 2 ANNI")
    print("=" * 108)
    print(f"{'Asset':8s} {'Config':22s} {'Ret%':>7} {'CAGR%':>6} {'Sharpe':>7} "
          f"{'Sortino':>8} {'MaxDD%':>7} {'PF':>6} {'WR%':>6} "
          f"{'Trades':>7} {'Fees$':>7}  Verdict")
    print("-" * 108)
    for r in all_results:
        print(f"{r['asset']:8s} {r['label']:22s} {r['total_return_pct']:>7.1f} "
              f"{r['cagr_pct']:>6.1f} {r['sharpe']:>7.3f} {r['sortino']:>8.3f} "
              f"{r['max_drawdown_pct']:>7.1f} {r['profit_factor']:>6.3f} "
              f"{r['win_rate_pct']:>6.1f} {r['n_trades']:>7} "
              f"{r['fee_cumulative_usd']:>7.2f}  {r['verdict']}")

    print("\nOutput salvati in output/")
    print("  output/4h_adx_experiment.csv")
    print("  output/4h_adx_experiment.json")
    print("  output/4h_adx_equity_curves.png")


if __name__ == "__main__":
    main()
