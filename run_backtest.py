"""Shark Exchange - Bollinger squeeze breakout backtest (single file).
Run: python run_backtest.py --source gate --symbols BTCUSDT,ETHUSDT --days 90
"""
import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yaml

"""Candle data: gate | mexc | bybit | weex (USDT perpetual futures) ya csv. Binance use nahi hota."""

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLS = ["open_time", "open", "high", "low", "close", "volume"]


_LOCK, _NEXT = threading.Lock(), {}
_GAP = {"mexc": 0.25, "gateio": 0.1, "bybit": 0.06, "weex": 0.2}      # exchange par min gap (sec), sab threads ke liye


def _throttle(url):
    for key, gap in _GAP.items():
        if key in url:
            with _LOCK:
                now = time.time()
                t = max(now, _NEXT.get(key, 0))
                _NEXT[key] = t + gap
            time.sleep(max(0, t - now))
            return


def _get(url, params=None):
    for k in range(4):
        _throttle(url)
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 + 2 * k); continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if k == 3: raise
            time.sleep(1 + k)
    raise RuntimeError("rate limited: " + url)


def _nat(sym, src):                       # internal "BTCUSDT" -> exchange ka symbol
    b = sym[:-4]
    return {"gate": f"{b}_USDT", "mexc": f"{b}_USDT", "bybit": sym, "weex": f"cmt_{sym.lower()}"}[src]


# ---------- candle adapters: [[open_time_ms, o, h, l, c, v], ...] ----------
def _gate(sym, tf, s, e):
    d = _get("https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
             {"contract": _nat(sym, "gate"), "interval": tf, "from": s // 1000, "to": e // 1000})
    return [[int(x["t"]) * 1000, x["o"], x["h"], x["l"], x["c"], x.get("v", 0)] for x in d]


_MEXC = {"5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60", "4h": "Hour4", "1d": "Day1"}
def _mexc(sym, tf, s, e):
    url = "https://contract.mexc.com/api/v1/contract/kline/" + _nat(sym, "mexc")
    for k in range(6):
        j = _get(url, {"interval": _MEXC[tf], "start": s // 1000, "end": e // 1000})
        d = j.get("data") if isinstance(j, dict) else None
        if isinstance(d, dict) and "time" in d:
            return [[int(t) * 1000, o, h, l, c, v] for t, o, h, l, c, v in
                    zip(d["time"], d["open"], d["high"], d["low"], d["close"], d["vol"])]
        msg = str(j)[:200]
        if isinstance(j, dict) and j.get("success") and not d:
            return []                                        # is range me candles nahi
        if "frequent" in msg.lower() or "510" in msg or "429" in msg:
            time.sleep(2 * (k + 1)); continue                # rate limit: ruk ke retry
        raise RuntimeError("MEXC " + msg)
    raise RuntimeError("MEXC rate limit: " + msg)


_BYBIT = {"5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}
def _bybit(sym, tf, s, e):
    d = _get("https://api.bybit.com/v5/market/kline",
             {"category": "linear", "symbol": sym, "interval": _BYBIT[tf],
              "start": s, "end": e, "limit": 1000})["result"]["list"]
    return [[int(x[0])] + x[1:6] for x in d]


def _weex(sym, tf, s, e):                 # UNVERIFIED: response format check karna
    d = _get("https://api-contract.weex.com/capi/v2/market/candles",
             {"symbol": _nat(sym, "weex"), "granularity": tf, "startTime": s, "endTime": e, "limit": 1000})
    return [[int(x[0])] + list(x[1:6]) for x in d]


ADAPTERS = {"gate": (_gate, 1900), "mexc": (_mexc, 1900), "bybit": (_bybit, 950), "weex": (_weex, 900)}


def list_symbols(src):
    """USDT perpetual pairs of that exchange, internal format BTCUSDT."""
    if src == "gate":
        d = _get("https://api.gateio.ws/api/v4/futures/usdt/contracts")
        out = [x["name"].replace("_", "") for x in d if not x.get("in_delisting")]
    elif src == "mexc":
        d = _get("https://contract.mexc.com/api/v1/contract/detail")["data"]
        out = [x["symbol"].replace("_", "") for x in d if x.get("quoteCoin") == "USDT" and x.get("state") == 0]
    elif src == "bybit":
        out, cur = [], ""
        while True:
            r = _get("https://api.bybit.com/v5/market/instruments-info",
                     {"category": "linear", "limit": 1000, "cursor": cur})["result"]
            out += [x["symbol"] for x in r["list"] if x["quoteCoin"] == "USDT"
                    and x["status"] == "Trading" and x.get("contractType") == "LinearPerpetual"]
            cur = r.get("nextPageCursor")
            if not cur: break
    elif src == "weex":                   # UNVERIFIED
        d = _get("https://api-contract.weex.com/capi/v2/market/contracts")
        out = [x["symbol"].replace("cmt_", "").upper() for x in d if str(x["symbol"]).endswith("usdt")]
    else:
        raise ValueError("list_symbols: source " + src)
    return sorted(s for s in out if s.endswith("USDT"))


def _fetch(src, sym, tf, s, e):
    fn, maxn = ADAPTERS[src]
    step, rows, cur = maxn * TF_MS[tf], [], s
    while cur < e:
        rows += fn(sym, tf, cur, min(cur + step - 1, e))
        cur += step
    df = pd.DataFrame(rows, columns=COLS)
    for c in COLS:
        df[c] = pd.to_numeric(df[c])
    return df


def get_candles(symbol, tf, cfg, refresh=False):
    """Sirf closed candles. cols: open_time(ms), open, high, low, close, volume."""
    src = cfg["source"]
    d = Path(cfg["csv_dir"]) if src == "csv" else Path(cfg["csv_dir"]) / src
    path = d / f"{symbol}_{tf}.csv"
    if src == "csv" or (path.exists() and not refresh):
        df = pd.read_csv(path)
    else:
        end = int(time.time() * 1000)
        df = _fetch(src, symbol, tf, end - int(cfg["days"] * 86_400_000), end)
        d.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    df = df[df.open_time + TF_MS[tf] <= int(time.time() * 1000)]
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def add_bb(df, period, std, lookback, quantile, min_bars):
    df = df.copy()
    m = df.close.rolling(period).mean()
    sd = df.close.rolling(period).std(ddof=0)
    df["mid"], df["up"], df["lo"] = m, m + std * sd, m - std * sd
    df["bw"] = (df.up - df.lo) / df.mid
    thr = df.bw.rolling(lookback).quantile(quantile)
    df["is_sq"] = df.bw <= thr
    df["squeeze_ok"] = df.is_sq.rolling(min_bars).sum() == min_bars
    df["vol_ma"] = df.volume.rolling(20).mean()
    return df


def _asof(base, htf, htf_tf, col):
    h = pd.DataFrame({"avail": htf.open_time + TF_MS[htf_tf], "v": col})
    m = pd.merge_asof(pd.DataFrame({"t": base.open_time}), h, left_on="t", right_on="avail", direction="backward")
    return m.v


def htf_flag(base, htf, htf_tf):
    """Base candle ke open par last *closed* HTF candle me squeeze tha ya nahi (no lookahead)."""
    return _asof(base, htf, htf_tf, htf.squeeze_ok.astype(bool)).fillna(False).astype(bool).to_numpy()


def htf_trend(base, htf, htf_tf, ema_len):
    """+1 agar last closed HTF candle EMA ke upar, -1 neeche, 0 abhi EMA ready nahi."""
    ema = htf.close.ewm(span=ema_len, adjust=False).mean()
    tr = pd.Series(np.where(htf.close > ema, 1, -1), index=htf.index)
    tr.iloc[:ema_len] = 0
    return _asof(base, htf, htf_tf, tr).fillna(0).astype(int).to_numpy()


def make_signals(base, flags, trend=None, vol_mult=0.0):
    """+1 long, -1 short, 0 none. Squeeze pichli candle tak thi, ab band tod di.
    trend: htf_trend array (long sirf uptrend me, short sirf downtrend me). vol_mult: breakout volume > mult x avg."""
    sq = base.squeeze_ok.shift(1, fill_value=False).astype(bool).to_numpy().copy()
    for f in flags:
        sq &= f
    long = sq & (base.close > base.up).to_numpy()
    short = sq & (base.close < base.lo).to_numpy()
    if vol_mult > 0:
        ok = (base.volume > vol_mult * base.vol_ma.shift(1)).to_numpy()
        long &= ok; short &= ok
    if trend is not None:
        long &= trend == 1; short &= trend == -1
    return np.where(long, 1, np.where(short, -1, 0))


def simulate(df, sig, t, sl_ratio=1.0):
    """Entry: signal candle ke agli candle ke open par. Initial SL = signal candle ki BB middle line.
    Partial TPs (t['tp_levels']): level hit hone par us qty ka profit book, SL = us TP price par.
    Conservative: ek candle me SL aur TP dono lage to SL pehle; SL shift agli candle se lagu."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    mid, ot = df.mid.to_numpy(), df.open_time.to_numpy()
    n, free, out = len(df), 0, []
    notional = t["margin_inr"] * t["leverage"]
    cost = 2 * (t["taker_fee_pct"] + t["slippage_pct"]) / 100
    lv = [(x["pct"] / 100, x["qty_pct"] / 100) for x in t["tp_levels"]]
    for i in np.flatnonzero(sig):
        if i + 1 >= n or i + 1 < free:
            continue
        side, e, m0 = int(sig[i]), o[i + 1], mid[i]
        if (side == 1 and m0 >= e) or (side == -1 and m0 <= e):
            continue
        sl0 = e + sl_ratio * (m0 - e)        # sl_ratio 1.0 = middle line, 0.5 = entry aur middle line ke beech
        if abs(e - sl0) / e > t["max_sl_pct"] / 100:
            continue
        tps = [e * (1 + side * p) for p, _ in lv]
        sl, k, rem, gross, reason, jx = sl0, 0, 1.0, 0.0, "EOD", n - 1
        done = False
        for j in range(i + 1, n):
            if (l[j] <= sl) if side == 1 else (h[j] >= sl):          # SL pehle
                gross += rem * side * (sl - e) / e
                reason, jx, done = ("SL" if k == 0 else f"SL@TP{k}"), j, True
                break
            new_sl = None
            while k < len(lv) and ((h[j] >= tps[k]) if side == 1 else (l[j] <= tps[k])):
                q = rem if k == len(lv) - 1 else min(lv[k][1], rem)
                gross += q * side * (tps[k] - e) / e
                rem -= q; new_sl = tps[k]; k += 1
            if new_sl is not None:
                sl = new_sl
            if k == len(lv):
                reason, jx, done = f"TP{k}", j, True
                break
        if not done:
            gross += rem * side * (c[-1] - e) / e
        pnl = max(notional * (gross - cost), -t["margin_inr"])
        out.append(dict(side="LONG" if side == 1 else "SHORT", entry_time=int(ot[i + 1]),
                        exit_time=int(ot[jx]), entry=e, sl_initial=sl0, tp_hits=k,
                        reason=reason, pnl_inr=pnl))
        free = jx + 1
    return out


def _stats(g):
    g = g.sort_values("exit_time")
    pnl = g.pnl_inr
    h1, h2 = g[g.half == 0].pnl_inr.sum(), g[g.half == 1].pnl_inr.sum()
    sym_ok = (g.groupby("symbol").pnl_inr.sum() > 0).mean() * 100 if "symbol" in g else float(pnl.sum() > 0) * 100
    eq = pnl.cumsum()
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = gp / gl if gl > 0 else np.inf
    checks = int(len(g) >= 100) + int(pf >= 1.3) + int(h1 > 0 and h2 > 0) + int(sym_ok >= 50)
    return pd.Series(dict(trades=len(g), win_rate_pct=round((pnl > 0).mean() * 100, 2),
                          tp1_hit_pct=round((g.tp_hits >= 1).mean() * 100, 1),
                          tp2_hit_pct=round((g.tp_hits >= 2).mean() * 100, 1),
                          tp3_hit_pct=round((g.tp_hits >= 3).mean() * 100, 1),
                          net_pnl_inr=round(pnl.sum(), 2), avg_trade_inr=round(pnl.mean(), 2),
                          profit_factor=round(pf, 3),
                          max_drawdown_inr=round((eq.cummax() - eq).max(), 2),
                          half1_pnl=round(h1, 2), half2_pnl=round(h2, 2),
                          symbols_profitable_pct=round(sym_ok, 1), checks_passed_of_4=checks))


def write_report(trades, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    if trades.empty:
        print("Koi trade nahi bana. Squeeze params ya symbols/days badlo.")
        return
    trades["half"] = (trades.entry_time > trades.entry_time.median()).astype(int)
    trades["entry_dt"] = pd.to_datetime(trades.entry_time, unit="ms")
    trades["exit_dt"] = pd.to_datetime(trades.exit_time, unit="ms")
    trades.to_csv(out / "trades.csv", index=False)
    summary = trades.groupby(["variant", "tf"]).apply(_stats, include_groups=False).reset_index()
    summary.to_csv(out / "summary.csv", index=False)
    trades.groupby(["variant", "symbol", "tf"]).apply(_stats, include_groups=False).reset_index() \
        .to_csv(out / "per_symbol.csv", index=False)
    trades.groupby(["variant", "tf", "reason"]).pnl_inr.agg(["count", "sum"]).round(2).reset_index() \
        .to_csv(out / "exit_reasons.csv", index=False)
    print(summary.to_string(index=False))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        for (v, tf), g in trades.groupby(["variant", "tf"]):
            g = g.sort_values("exit_time")
            ax.plot(g.exit_dt, g.pnl_inr.cumsum(), label=f"{v} {tf}")
        ax.set_ylabel("Cumulative PnL (INR)"); ax.legend(); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / "equity.png", dpi=120)
    except Exception as ex:
        print("Plot skip:", ex)


def run_symbol(sym, cfg, refresh):
    bb, sq, t = cfg["bb"], cfg["squeeze"], cfg["trade"]
    prep = lambda tf: add_bb(get_candles(sym, tf, cfg, refresh), bb["period"], bb["std"],
                             sq["lookback"], sq["quantile"], sq["min_bars"])
    tcfg, variants = cfg["trend"], cfg["variants"]
    if cfg["mode"] == "mtf":
        base_tf = cfg["base_tf"]
        base = prep(base_tf)
        flags = [htf_flag(base, prep(tf), tf) for tf in cfg["confluence_tfs"] if tf != base_tf]
        jobs = [(base_tf, base, flags)]
    else:
        jobs = [(tf, prep(tf), []) for tf in cfg["single_tfs"]]
    need_trend = any(v.get("trend") for v in variants)
    tdf = get_candles(sym, tcfg["tf"], cfg, refresh) if need_trend else None
    out = []
    for tf, d, flags in jobs:
        tr = htf_trend(d, tdf, tcfg["tf"], tcfg["ema"]) if need_trend else None
        for v in variants:
            sig = make_signals(d, flags, tr if v.get("trend") else None, v.get("volume_mult", 0.0))
            for x in simulate(d, sig, t, v.get("sl_ratio", 1.0)):
                out.append(dict(symbol=sym, tf=tf, variant=v["name"], **x))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", help="comma separated, e.g. BTCUSDT,ETHUSDT")
    ap.add_argument("--days", type=int)
    ap.add_argument("--source", choices=list(ADAPTERS) + ["csv"])
    ap.add_argument("--refresh", action="store_true", help="data dobara download")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    if a.days: cfg["days"] = a.days
    if a.source: cfg["source"] = a.source
    cfg.setdefault("trend", {"tf": "4h", "ema": 50})
    cfg.setdefault("variants", [{"name": "baseline"}])
    assert abs(sum(x["qty_pct"] for x in cfg["trade"]["tp_levels"]) - 100) < 1e-9, "tp_levels qty_pct ka sum 100 hona chahiye"
    syms = a.symbols.split(",") if a.symbols else cfg["symbols"]
    if isinstance(syms, str) and syms.endswith(".txt"):
        syms = [s.strip() for s in open(syms) if s.strip()]
    elif syms == "all":
        syms = list_symbols(cfg["source"])
    print(f"{len(syms)} symbols | source={cfg['source']} | mode={cfg['mode']}")
    def safe(s):
        try:
            return run_symbol(s, cfg, a.refresh)
        except Exception as ex:
            print(f"[skip] {s}: {ex}"); return []
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(safe, syms))
    trades = pd.DataFrame([x for r in res for x in r])
    write_report(trades, a.out)


if __name__ == "__main__":
    main()
