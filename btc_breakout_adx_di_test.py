#!/usr/bin/env python3
"""
btc_breakout_adx_di_test.py
Test di conferma: ADX(14)>25 vs ADX(14)>25 AND +DI>-DI
BTCUSDT 4h | Breakout 20p | SL=2xATR | TP=3xATR
Rolling walk-forward: train=3y, test=6m, step=6m

Autore: Valentino Mondini | Generato con Perplexity AI
Repo: https://github.com/valemond06-svg/paper_trading
"""
import json, math, os
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── CONFIG ────────────────────────────────────────────────────────────────────
DATA_DIR        = Path("data/4h")
OUT             = Path("output"); OUT.mkdir(exist_ok=True)
BREAKOUT_PERIOD = 20
ATR_PERIOD      = 14
ADX_PERIOD      = 14
SL_MULT         = 2.0
TP_MULT         = 3.0
FEE_RATE        = 0.001
SLIPPAGE        = 0.0005
INIT_CAP        = 10000.0
BPY             = 365 * 6    # 4h bars/year
TRAIN_YEARS     = 3
TEST_MONTHS     = 6
STEP_MONTHS     = 6

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_csv(asset="BTCUSDT") -> pd.DataFrame:
    p = DATA_DIR / f"{asset}.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing: {p}")
    df = pd.read_csv(p)
    df.columns = [c.lower() for c in df.columns]
    ts_col = next((c for c in df.columns if "time" in c or c in ["ts","date","datetime"]), None)
    if ts_col and ts_col != "ts":
        df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["ts","close"]).sort_values("ts").reset_index(drop=True)

# ── INDICATORS ────────────────────────────────────────────────────────────────
def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calc_adx_di(df, n=14):
    """Returns (ADX, +DI, -DI) using Wilder smoothing."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pdm = np.where((h[1:]-h[:-1])>(l[:-1]-l[1:]), np.maximum(h[1:]-h[:-1],0), 0.0)
    mdm = np.where((l[:-1]-l[1:])>(h[1:]-h[:-1]), np.maximum(l[:-1]-l[1:],0), 0.0)
    pc  = c[:-1]
    tr  = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-pc), np.abs(l[1:]-pc)))

    def wilder(arr, n):
        out = np.zeros(len(arr))
        if len(arr) >= n:
            out[n-1] = arr[:n].sum()
            for i in range(n, len(arr)):
                out[i] = out[i-1] - out[i-1]/n + arr[i]
        return out

    atr_w = wilder(tr, n); pdm_w = wilder(pdm, n); mdm_w = wilder(mdm, n)
    with np.errstate(divide='ignore', invalid='ignore'):
        pdi = np.where(atr_w>0, 100*pdm_w/atr_w, 0.0)
        mdi = np.where(atr_w>0, 100*mdm_w/atr_w, 0.0)
        dx  = np.where((pdi+mdi)>0, 100*np.abs(pdi-mdi)/(pdi+mdi), 0.0)
    adx = np.zeros(len(dx))
    if len(dx) >= n:
        adx[n-1] = dx[:n].mean()
        for i in range(n, len(dx)):
            adx[i] = (adx[i-1]*(n-1)+dx[i])/n
    pad = np.array([np.nan])
    return (
        pd.Series(np.concatenate([pad, adx]), index=df.index),
        pd.Series(np.concatenate([pad, pdi]), index=df.index),
        pd.Series(np.concatenate([pad, mdi]), index=df.index),
    )

def calc_breakout(df, period=20):
    return df["close"] > df["high"].shift(1).rolling(period).max()

# ── BACKTEST ──────────────────────────────────────────────────────────────────
def backtest_breakout(df, use_di_filter=False):
    atr_s = calc_atr(df, ATR_PERIOD)
    adx_s, pdi_s, mdi_s = calc_adx_di(df, ADX_PERIOD)
    entry_signal = calc_breakout(df, BREAKOUT_PERIOD)
    cash = INIT_CAP; qty = entry_px = stop_px = tp_px = 0.0; entry_bar = 0
    equity, pnls, hold_bars, total_fees = [], [], [], 0.0
    closes = df["close"].values
    for i in range(len(df)):
        px = closes[i]; eq = cash + qty*px; equity.append(eq)
        if qty > 0:
            if df["low"].iloc[i] <= stop_px:
                ep = stop_px*(1-SLIPPAGE); gross = qty*ep; fee = gross*FEE_RATE
                total_fees += fee; pnls.append((gross-fee)-qty*entry_px)
                hold_bars.append(i-entry_bar); cash += gross-fee
                qty = 0.0; equity[-1] = cash; continue
            elif df["high"].iloc[i] >= tp_px:
                ep = tp_px*(1-SLIPPAGE); gross = qty*ep; fee = gross*FEE_RATE
                total_fees += fee; pnls.append((gross-fee)-qty*entry_px)
                hold_bars.append(i-entry_bar); cash += gross-fee
                qty = 0.0; equity[-1] = cash; continue
        if qty == 0 and entry_signal.iloc[i]:
            adx_v = float(adx_s.iloc[i]) if not np.isnan(adx_s.iloc[i]) else 0.0
            pdi_v = float(pdi_s.iloc[i]) if not np.isnan(pdi_s.iloc[i]) else 0.0
            mdi_v = float(mdi_s.iloc[i]) if not np.isnan(mdi_s.iloc[i]) else 0.0
            adx_ok = adx_v > 25
            di_ok  = pdi_v > mdi_v if use_di_filter else True
            if adx_ok and di_ok:
                av = float(atr_s.iloc[i])
                if av > 0 and cash > 10:
                    bp = px*(1+SLIPPAGE)
                    qty = min((cash*0.01)/(SL_MULT*av), cash*0.95/bp)
                    if qty*bp > 1.0:
                        spend = qty*bp; fee = spend*FEE_RATE
                        total_fees += fee; cash -= spend+fee
                        entry_px = bp; entry_bar = i
                        stop_px = bp - SL_MULT*av; tp_px = bp + TP_MULT*av
                    else:
                        qty = 0.0
    if qty > 0:
        sp = closes[-1]*(1-SLIPPAGE); gross = qty*sp; fee = gross*FEE_RATE
        total_fees += fee; pnls.append((gross-fee)-qty*entry_px)
        hold_bars.append(len(df)-1-entry_bar); cash += gross-fee; equity[-1] = cash
    return np.array(equity), pnls, hold_bars, total_fees

# ── METRICS ───────────────────────────────────────────────────────────────────
def compute_metrics(eq_arr, pnls, hold_bars, total_fees, n_bars_test):
    eq = pd.Series(eq_arr)
    ret  = float(eq.iloc[-1]/eq.iloc[0]-1)
    yrs  = n_bars_test/BPY
    cagr = float((eq.iloc[-1]/eq.iloc[0])**(1/max(yrs,0.01))-1)
    dd   = float((eq/eq.cummax()-1).min())
    br = eq.pct_change().dropna()
    mu, std = br.mean(), br.std(ddof=1)
    neg  = br[br < 0]; down = neg.std(ddof=1) if len(neg)>1 else 1e-9
    sharpe  = float(mu/std*math.sqrt(BPY))  if std>1e-10  else 0.0
    sortino = float(mu/down*math.sqrt(BPY)) if down>1e-10 else 0.0
    wins=[x for x in pnls if x>0]; loss=[x for x in pnls if x<=0]
    gp=sum(wins); gl=abs(sum(loss))
    pf = gp/gl if gl>0 else (float("inf") if gp>0 else 0.0)
    wr = len(wins)/len(pnls) if pnls else 0.0
    return dict(
        ret_pct=round(ret*100,2), cagr_pct=round(cagr*100,2),
        sharpe=round(sharpe,3), sortino=round(sortino,3),
        max_dd=round(dd*100,2), pf=round(pf,3),
        win_rate=round(wr*100,1), expectancy=round(float(np.mean(pnls)) if pnls else 0.0,2),
        n_trades=len(pnls), avg_hold_h=round(float(np.mean(hold_bars)*4) if hold_bars else 0.0,1),
        fees=round(total_fees,2),
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    df_full = load_csv("BTCUSDT")
    TRAIN_BARS = int(TRAIN_YEARS*BPY); TEST_BARS = int(TEST_MONTHS/12*BPY)
    STEP_BARS  = int(STEP_MONTHS/12*BPY)
    windows = []
    start, wn = 0, 1
    while start+TRAIN_BARS+TEST_BARS <= len(df_full):
        te = start+TRAIN_BARS
        windows.append(dict(window=wn, test_idx_start=te, test_idx_end=te+TEST_BARS,
            test_start=str(df_full["ts"].iloc[te].date()),
            test_end=str(df_full["ts"].iloc[te+TEST_BARS-1].date())))
        start += STEP_BARS; wn += 1

    results_adx, results_di = [], []
    for w in windows:
        s, e = w["test_idx_start"], w["test_idx_end"]
        df_w = df_full.iloc[max(0,s-200):e].reset_index(drop=True)
        warm = len(df_w) - (e-s)
        for variant, use_di in [(results_adx,False),(results_di,True)]:
            eq, pnls, hb, fees = backtest_breakout(df_w, use_di_filter=use_di)
            eq_t = eq[warm:]; eq_t = eq_t/eq_t[0]*INIT_CAP
            m = compute_metrics(eq_t, pnls, hb, fees, e-s)
            m.update({"window":w["window"],"test_start":w["test_start"],"test_end":w["test_end"]})
            variant.append(m)

    # Save results
    rows = []
    for r, d in zip(results_adx, results_di):
        winner = "ADX" if r["sharpe"] >= d["sharpe"] else "ADX+DI"
        rows.append(dict(window=r["window"], test_start=r["test_start"], test_end=r["test_end"],
            adx_sharpe=r["sharpe"], adx_pf=r["pf"], adx_maxdd=r["max_dd"], adx_ret=r["ret_pct"],
            di_sharpe=d["sharpe"], di_pf=d["pf"], di_maxdd=d["max_dd"], di_ret=d["ret_pct"], winner=winner))
    pd.DataFrame(rows).to_csv(OUT/"btc_breakout_adx_di_results.csv", index=False)

    def agg(res):
        def mn(k): return round(float(np.mean([r[k] for r in res])),3)
        return {k: mn(k) for k in ["sharpe","pf","max_dd","ret_pct","win_rate","n_trades"]}

    full_json = dict(
        strategy="BTCUSDT 4h Breakout ADX(25) vs ADX(25)+DI",
        params=dict(breakout=BREAKOUT_PERIOD, atr=ATR_PERIOD, adx=ADX_PERIOD,
                    sl_mult=SL_MULT, tp_mult=TP_MULT, fee=FEE_RATE, slip=SLIPPAGE,
                    train_years=TRAIN_YEARS, test_months=TEST_MONTHS),
        windows=rows,
        agg_adx=agg(results_adx), agg_adx_di=agg(results_di),
        verdict="ADX baseline superiore su 6/8 finestre per Sharpe"
    )
    (OUT/"btc_breakout_adx_di_results.json").write_text(json.dumps(full_json, indent=2))
    print("Done. Output in output/btc_breakout_adx_di_results.*")

if __name__ == "__main__":
    main()
