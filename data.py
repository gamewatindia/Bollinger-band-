"""Candle data: gate | mexc | bybit | weex (USDT perpetual futures) ya csv. Binance use nahi hota."""
import time
from pathlib import Path
import pandas as pd
import requests

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLS = ["open_time", "open", "high", "low", "close", "volume"]


def _get(url, params=None):
    for k in range(4):
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
    d = _get("https://contract.mexc.com/api/v1/contract/kline/" + _nat(sym, "mexc"),
             {"interval": _MEXC[tf], "start": s // 1000, "end": e // 1000})["data"]
    return [[int(t) * 1000, o, h, l, c, v] for t, o, h, l, c, v in
            zip(d["time"], d["open"], d["high"], d["low"], d["close"], d["vol"])]


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
        time.sleep(0.12)
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
