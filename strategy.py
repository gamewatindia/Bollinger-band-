import numpy as np
import pandas as pd
from .data import TF_MS


def add_bb(df, period, std, lookback, quantile, min_bars):
    df = df.copy()
    m = df.close.rolling(period).mean()
    sd = df.close.rolling(period).std(ddof=0)
    df["mid"], df["up"], df["lo"] = m, m + std * sd, m - std * sd
    df["bw"] = (df.up - df.lo) / df.mid
    thr = df.bw.rolling(lookback).quantile(quantile)
    df["is_sq"] = df.bw <= thr
    df["squeeze_ok"] = df.is_sq.rolling(min_bars).sum() == min_bars
    return df


def htf_flag(base, htf, htf_tf):
    """Base candle ke open par, last *closed* HTF candle me squeeze tha ya nahi (no lookahead)."""
    h = pd.DataFrame({"avail": htf.open_time + TF_MS[htf_tf], "f": htf.squeeze_ok.astype(bool)})
    b = pd.DataFrame({"t": base.open_time})
    m = pd.merge_asof(b, h, left_on="t", right_on="avail", direction="backward")
    return m.f.fillna(False).astype(bool).to_numpy()


def make_signals(base, flags):
    """+1 long, -1 short, 0 none. Squeeze pichli candle tak thi, ab band tod di."""
    sq = base.squeeze_ok.shift(1, fill_value=False).astype(bool).to_numpy().copy()
    for f in flags:
        sq &= f
    long = sq & (base.close > base.up).to_numpy()
    short = sq & (base.close < base.lo).to_numpy()
    return np.where(long, 1, np.where(short, -1, 0))
