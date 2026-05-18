#!/usr/bin/env python3
"""
offline_research.py – Laboratorio di ricerca offline: Baseline vs 3 Varianti SMA
Autore: generato da Perplexity AI per paper_trading repo
Usa i CSV locali in data/{1h}/ — non richiede connessione.
"""
import json, math, os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ── CONFIG ────────────────────────────────────────────────────────────────────
DATA_DIR   = Path("data/1h")
OUT        = Path("output"); OUT.mkdir(exist_ok=True)
FAST, SLOW, REGIME = 12, 34, 144
FEE_RATE   = 0.001
SLIPPAGE   = 0.0005
INIT_CAP   = 1000.0
ALLOC      = 0.25
MIN_TRADE  = 5.0
ATR_PERIOD = 14
BPY        = 365 * 24

ASSETS_BASELINE = ["BNBUSDT"]          # asset live attuali
ASSETS_V3       = ["BNBUSDT","BTCUSDT","ETHUSDT"]

# Walk-forward: train ~4 anni (35040 barre 1h), test ~2 anni (17520 barre)
TRAIN_BARS = 365 * 24 * 4
TEST_BARS  = 365 * 24 * 2

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_csv(asset: str) -> pd.DataFrame:
    p = DATA_DIR / f"{asset}.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing: {p}")
    df = pd.read_csv(p)
    df.columns = [c.lower() for c in df.columns]
    ts_col = next((c for c in df.columns if "time" in c or c == "ts" or c == "date"), None)
    if ts_col and ts_col != "ts":
        df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["ts","close"]).sort_values("ts").reset_index(drop=True)
    return df

# ── INDICATORS ────────────────────────────────────────────────────────────────
def sma(s, n): return s.rolling(n).mean()

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ── SIGNALS ───────────────────────────────────────────────────────────────────
def baseline_signal(df):
    """Segnale live attuale: 1 su ogni candela bullish (bug re-entry)."""
    c = df["close"]
    return ((sma(c,FAST) > sma(c,SLOW)) & (c > sma(c,REGIME))).astype(int)

def crossover_signals(df):
    """True crossover: entry solo sul fronte 0→1, exit sul fronte 1→0."""
    bull = baseline_signal(df)
    diff = bull - bull.shift(1).fillna(0)
    return (diff == 1), (diff == -1)

# ── BACKTEST ENGINES ──────────────────────────────────────────────────────────
def bt_baseline(df):
    sig = baseline_signal(df)
    cash, qty, entry = INIT_CAP, 0.0, 0.0
    equity, pnls, ipb = [], [], 0
    for i in range(len(df)):
        px = float(df["close"].iloc[i])
        eq = cash + qty * px; equity.append(eq)
        if qty > 0: ipb += 1
        if sig.iloc[i] == 1 and cash > MIN_TRADE:
            spend = min(eq * ALLOC, cash)
            if spend >= MIN_TRADE:
                bp = px*(1+SLIPPAGE); fee = spend*FEE_RATE
                qty += (spend-fee)/bp; cash -= spend
                if entry == 0: entry = bp
        elif sig.iloc[i] == 0 and qty > 0:
            sp = px*(1-SLIPPAGE); gross = qty*sp; fee = gross*FEE_RATE
            pnls.append(gross-fee - qty*entry); cash += gross-fee; qty=0.0; entry=0.0
    if qty > 0:
        sp = float(df["close"].iloc[-1])*(1-SLIPPAGE)
        gross = qty*sp; fee = gross*FEE_RATE
        pnls.append(gross-fee - qty*entry); cash += gross-fee
    return np.array(equity), pnls, ipb

def bt_v1(df):
    entry_s, exit_s = crossover_signals(df)
    cash, qty, entry = INIT_CAP, 0.0, 0.0
    equity, pnls, ipb = [], [], 0
    stop_px = tp_px = 0.0
    sl_pct, tp_pct = 0.02, 0.03
    for i in range(len(df)):
        px = float(df["close"].iloc[i]); eq = cash+qty*px; equity.append(eq)
        if qty > 0: ipb += 1
        if qty > 0 and (px<=stop_px or px>=tp_px):
            sp=px*(1-SLIPPAGE); gross=qty*sp; fee=gross*FEE_RATE
            pnls.append(gross-fee-qty*entry); cash+=gross-fee; qty=0.0; entry=0.0
        if entry_s.iloc[i] and qty==0 and cash>MIN_TRADE:
            spend=min(eq*ALLOC,cash)
            if spend>=MIN_TRADE:
                bp=px*(1+SLIPPAGE); fee=spend*FEE_RATE
                qty=(spend-fee)/bp; cash-=spend; entry=bp
                stop_px=entry*(1-sl_pct); tp_px=entry*(1+tp_pct)
        elif exit_s.iloc[i] and qty>0:
            sp=px*(1-SLIPPAGE); gross=qty*sp; fee=gross*FEE_RATE
            pnls.append(gross-fee-qty*entry); cash+=gross-fee; qty=0.0; entry=0.0
    if qty>0:
        sp=float(df["close"].iloc[-1])*(1-SLIPPAGE)
        gross=qty*sp; fee=gross*FEE_RATE
        pnls.append(gross-fee-qty*entry); cash+=gross-fee
    return np.array(equity), pnls, ipb

def bt_v2(df, atr_sl=1.5, atr_tp=2.5):
    entry_s, exit_s = crossover_signals(df)
    atr_s = atr(df, ATR_PERIOD)
    cash, qty, entry = INIT_CAP, 0.0, 0.0
    equity, pnls, ipb = [], [], 0
    stop_px = tp_px = 0.0
    for i in range(len(df)):
        px = float(df["close"].iloc[i]); eq = cash+qty*px; equity.append(eq)
        if qty > 0: ipb += 1
        if qty > 0 and (px<=stop_px or px>=tp_px):
            sp=px*(1-SLIPPAGE); gross=qty*sp; fee=gross*FEE_RATE
            pnls.append(gross-fee-qty*entry); cash+=gross-fee; qty=0.0; entry=0.0
        if entry_s.iloc[i] and qty==0 and cash>MIN_TRADE:
            av = float(atr_s.iloc[i])
            if not (np.isnan(av) or av<=0):
                spend=min(eq*ALLOC,cash)
                if spend>=MIN_TRADE:
                    bp=px*(1+SLIPPAGE); fee=spend*FEE_RATE
                    qty=(spend-fee)/bp; cash-=spend; entry=bp
                    stop_px=entry-atr_sl*av; tp_px=entry+atr_tp*av
        elif exit_s.iloc[i] and qty>0:
            sp=px*(1-SLIPPAGE); gross=qty*sp; fee=gross*FEE_RATE
            pnls.append(gross-fee-qty*entry); cash+=gross-fee; qty=0.0; entry=0.0
    if qty>0:
        sp=float(df["close"].iloc[-1])*(1-SLIPPAGE)
        gross=qty*sp; fee=gross*FEE_RATE
        pnls.append(gross-fee-qty*entry); cash+=gross-fee
    return np.array(equity), pnls, ipb

# ── METRICS ───────────────────────────────────────────────────────────────────
def compute_metrics(eq_arr, pnls, ipb, label):
    eq = pd.Series(eq_arr); n = len(eq)
    ret  = float(eq.iloc[-1]/eq.iloc[0]-1)
    yrs  = n/BPY
    cagr = float((eq.iloc[-1]/eq.iloc[0])**(1/yrs)-1)
    dd   = float((eq/eq.cummax()-1).min())
    br   = eq.pct_change().dropna()
    mu, std = br.mean(), br.std(ddof=0)
    neg  = br[br<0]; down = neg.std(ddof=0) if len(neg)>1 else 1e-9
    sharpe  = float(mu/std*math.sqrt(BPY))  if std>1e-10  else 0.0
    sortino = float(mu/down*math.sqrt(BPY)) if down>1e-10 else 0.0
    w  = sum(1 for x in pnls if x>0)
    gp = sum(x for x in pnls if x>0)
    gl = abs(sum(x for x in pnls if x<0))
    pf = gp/gl if gl>0 else (float("inf") if gp>0 else 0.0)
    wr = w/len(pnls) if pnls else 0.0
    exp = float(np.mean(pnls)) if pnls else 0.0
    ah  = ipb/len(pnls) if pnls else 0.0
    return dict(
        label=label,
        total_return_pct=round(ret*100,2), cagr_pct=round(cagr*100,2),
        sharpe=round(sharpe,3), sortino=round(sortino,3),
        max_drawdown_pct=round(dd*100,2), profit_factor=round(pf,3),
        win_rate_pct=round(wr*100,2), expectancy_usd=round(exp,4),
        n_trades=len(pnls), avg_hold_h=round(ah,1)
    )

# ── WALK-FORWARD SPLIT ────────────────────────────────────────────────────────
def wf_split(df):
    total = len(df)
    tb = TRAIN_BARS if total >= TRAIN_BARS+TEST_BARS else int(total*4/6)
    te = TEST_BARS  if total >= TRAIN_BARS+TEST_BARS else total-tb
    return df.iloc[:tb].reset_index(drop=True), df.iloc[tb:tb+te].reset_index(drop=True)

# ── DECISION LOGIC ────────────────────────────────────────────────────────────
def decision(r, baseline_r):
    s, pf, dd = r["sharpe"], r["profit_factor"], r["max_drawdown_pct"]
    if s > 1.0 and pf > 1.3 and dd > -20.0:
        return "✅ PROMETTENTE → integrabile nel live"
    elif s > baseline_r["sharpe"] or pf > baseline_r["profit_factor"]:
        return "⚠️  MIGLIORAMENTO PARZIALE → ancora insufficiente"
    else:
        return "❌ DA ABBANDONARE"

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    results = []
    curves  = {}

    # Baseline & V1, V2 su BNBUSDT 1h
    for asset in ASSETS_BASELINE:
        df = load_csv(asset)
        _, test = wf_split(df)
        print(f"\n[{asset}] test bars={len(test)}  {test['ts'].iloc[0].date()} → {test['ts'].iloc[-1].date()}")

        for name, fn in [("Baseline", bt_baseline), ("V1_TrueCrossover", bt_v1), ("V2_ATR", bt_v2)]:
            eq, pnls, ipb = fn(test)
            m = compute_metrics(eq, pnls, ipb, name)
            m["asset"] = asset; m["timeframe"] = "1h"
            results.append(m)
            curves[f"{asset}_{name}"] = (test["ts"].values, eq)
            print(f"  {name}: ret={m['total_return_pct']}% sharpe={m['sharpe']} "
                  f"pf={m['profit_factor']} dd={m['max_drawdown_pct']}% trades={m['n_trades']}")

    # V3: multi-asset portfolio (V2 logic su tutti e 3)
    v3_equities = {}; v3_pnls_all = []; v3_ipb = 0
    for asset in ASSETS_V3:
        try:
            df = load_csv(asset)
            _, test = wf_split(df)
            eq, pnls, ipb = bt_v2(test)
            v3_equities[asset] = (test["ts"].values, eq)
            v3_pnls_all.extend(pnls); v3_ipb += ipb
        except FileNotFoundError as e:
            print(f"  [WARNING] {e}")

    if v3_equities:
        min_l = min(len(v) for _, v in v3_equities.values())
        eq_port = np.zeros(min_l)
        for sym, (ts, eq) in v3_equities.items():
            ratio = (INIT_CAP/len(v3_equities))/eq[0]
            eq_port += eq[:min_l]*ratio
        # usa ts del primo asset disponibile
        first_ts = list(v3_equities.values())[0][0]
        m3 = compute_metrics(eq_port, v3_pnls_all, v3_ipb, "V3_MultiAsset_Portfolio")
        m3["asset"] = "+".join(ASSETS_V3); m3["timeframe"] = "1h"
        results.append(m3)
        curves["V3_Portfolio"] = (first_ts[:min_l], eq_port)
        print(f"\n  V3 Portfolio: ret={m3['total_return_pct']}% sharpe={m3['sharpe']} "
              f"pf={m3['profit_factor']} dd={m3['max_drawdown_pct']}% trades={m3['n_trades']}")

    # ── DECISION VERDICTS ──
    baseline_r = next((r for r in results if r["label"]=="Baseline"), results[0])
    for r in results:
        r["verdict"] = decision(r, baseline_r)

    # ── SAVE OUTPUTS ──
    df_out = pd.DataFrame(results)
    df_out.to_csv(OUT/"research_comparison.csv", index=False)
    (OUT/"research_comparison.json").write_text(json.dumps(results, indent=2, default=str))

    # ── EQUITY CHART ──
    colors  = {"Baseline":"#e74c3c","V1_TrueCrossover":"#3498db",
               "V2_ATR":"#2ecc71","V3_Portfolio":"#f39c12"}
    dashes  = {"Baseline":"solid","V1_TrueCrossover":"solid",
               "V2_ATR":"dash","V3_Portfolio":"dot"}
    fig = go.Figure()
    for key, (ts, eq) in curves.items():
        nm = key.replace(f"{ASSETS_BASELINE[0]}_","")
        fig.add_trace(go.Scatter(
            x=ts, y=eq, name=nm,
            line=dict(color=colors.get(nm,"#aaa"), width=2.5, dash=dashes.get(nm,"solid"))
        ))
    fig.add_hline(y=INIT_CAP, line_dash="longdash", line_color="rgba(255,255,255,0.3)")
    fig.update_layout(title={"text":
        "OOS Equity Curves – Baseline vs Varianti SMA Crossover<br>"
        "<span style='font-size:16px;font-weight:normal'>"
        "Walk-Forward Test (~2 anni) | Fee 0.1% | Slippage 0.05%</span>"},
        legend=dict(orientation="h",yanchor="top",y=-0.12,xanchor="center",x=0.5))
    fig.update_xaxes(title_text="Data")
    fig.update_yaxes(title_text="Equity ($)")
    fig.write_image(OUT/"research_equity_curves.png")

    # ── PRINT TABLE ──
    print("\n" + "="*82)
    print("TABELLA COMPARATIVA – METRICHE OOS (TEST SET ~2 ANNI)")
    print("="*82)
    print(f"{'Label':25s} {'Ret%':>7} {'Sharpe':>7} {'Sortino':>8} {'MaxDD%':>8} "
          f"{'PF':>6} {'WR%':>6} {'Exp$':>7} {'Trades':>7} {'Verdict'}")
    print("-"*82)
    for r in results:
        print(f"{r['label']:25s} {r['total_return_pct']:>7.1f} {r['sharpe']:>7.3f} "
              f"{r['sortino']:>8.3f} {r['max_drawdown_pct']:>8.1f} "
              f"{r['profit_factor']:>6.3f} {r['win_rate_pct']:>6.1f} "
              f"{r['expectancy_usd']:>7.4f} {r['n_trades']:>7}  {r['verdict']}")
    print("\nOutput salvati in output/")
    print("  - output/research_comparison.csv")
    print("  - output/research_comparison.json")
    print("  - output/research_equity_curves.png")

if __name__ == "__main__":
    main()
