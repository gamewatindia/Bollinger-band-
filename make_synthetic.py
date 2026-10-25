"""Offline smoke-test: random-walk data with volatility regimes -> data/SYM_TF.csv"""
import numpy as np, pandas as pd
from pathlib import Path
from sharkbt.data import TF_MS
rng = np.random.default_rng(1)
Path("data").mkdir(exist_ok=True)
end = (pd.Timestamp.now("UTC").floor("D") - pd.Timedelta(days=1)).value // 10**6
for sym in ["AAAUSDT", "BBBUSDT"]:
    n = 60 * 96
    vol = np.repeat(rng.choice([0.0005, 0.004], n // 200 + 1), 200)[:n]
    p = 100 * np.exp(np.cumsum(rng.normal(0, vol)))
    base = pd.DataFrame({"open_time": end - (n - np.arange(n)) * TF_MS["15m"], "close": p})
    base["open"] = base.close.shift(1).fillna(base.close)
    spread = np.abs(rng.normal(0, vol)) * p
    base["high"] = base[["open", "close"]].max(axis=1) + spread
    base["low"] = base[["open", "close"]].min(axis=1) - spread
    base["volume"] = 1.0
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    base[cols].to_csv(f"data/{sym}_15m.csv", index=False)
    for tf, k in {"1h": 4, "4h": 16}.items():
        g = base.groupby(base.index // k).agg(open_time=("open_time", "first"), open=("open", "first"),
            high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
        g[cols].to_csv(f"data/{sym}_{tf}.csv", index=False)
