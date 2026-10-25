import numpy as np, pandas as pd
from unittest import mock
from sharkbt.engine import simulate
from sharkbt import data

T = dict(margin_inr=1000, leverage=10, taker_fee_pct=0, slippage_pct=0, max_sl_pct=8,
         tp_levels=[dict(pct=1, qty_pct=25), dict(pct=2, qty_pct=50), dict(pct=5, qty_pct=25)])

def mk(rows, side_mid=98.0):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = np.arange(len(df)) * 900_000
    df["mid"] = side_mid
    return df

def test_long_all_tps():
    df = mk([[100, 100, 100, 100], [100, 100.5, 99.9, 100], [100, 101.2, 99.9, 101], [101, 102.5, 101.5, 102], [102, 105.5, 103, 105]])
    sig = np.array([1, 0, 0, 0, 0])
    tr = simulate(df, sig, T)[0]
    assert tr["reason"] == "TP3" and tr["tp_hits"] == 3
    assert abs(tr["pnl_inr"] - 250) < 1e-6, tr           # .25*1%+.5*2%+.25*5% = 2.5% of 10k

def test_sl_moves_to_tp1():
    df = mk([[100, 100, 100, 100], [100, 100.5, 99.9, 100], [100, 101.2, 99.9, 101], [101, 101.5, 100.9, 101]])
    tr = simulate(df, np.array([1, 0, 0, 0]), T)[0]
    assert tr["reason"] == "SL@TP1" and abs(tr["pnl_inr"] - 100) < 1e-6, tr   # poori position 1% par

def test_sl_moves_to_tp2():
    df = mk([[100, 100, 100, 100], [100, 100.5, 99.9, 100], [100, 102.5, 99.9, 102], [102, 102.2, 101.9, 102]])
    tr = simulate(df, np.array([1, 0, 0, 0]), T)[0]   # same candle me TP1+TP2; SL next candle se TP2 par
    assert tr["reason"] == "SL@TP2" and abs(tr["pnl_inr"] - (.25 * 100 + .75 * 200)) < 1e-6, tr

def test_initial_sl_and_short():
    df = mk([[100, 100, 100, 100], [100, 100.5, 97.5, 98]])
    assert abs(simulate(df, np.array([1, 0]), T)[0]["pnl_inr"] + 200) < 1e-6   # SL 98 => -2% => -200
    df = mk([[100, 100, 100, 100], [100, 100.2, 98.9, 99], [99, 98.9, 97.8, 98], [98, 97.9, 94.9, 95]], side_mid=102.0)
    tr = simulate(df, np.array([-1, 0, 0, 0]), T)[0]
    assert tr["reason"] == "TP3" and abs(tr["pnl_inr"] - 250) < 1e-6, tr

def test_adapters_parse():
    ms = 1_700_000_000_000
    fake = {
        "gate": [{"t": ms // 1000, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": 10}],
        "mexc": {"data": {"time": [ms // 1000], "open": [1], "high": [2], "low": [.5], "close": [1.5], "vol": [10]}},
        "bybit": {"result": {"list": [[str(ms), "1", "2", "0.5", "1.5", "10", "15"]]}},
    }
    for src, fn in (("gate", data._gate), ("mexc", data._mexc), ("bybit", data._bybit)):
        with mock.patch.object(data, "_get", return_value=fake[src]):
            r = fn("ABCUSDT", "15m", ms, ms + 1000)
        assert r[0][0] == ms and float(r[0][4]) == 1.5, (src, r)
    assert data._nat("ABCUSDT", "gate") == "ABC_USDT" and data._nat("ABCUSDT", "weex") == "cmt_abcusdt"

if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); print("ok", k)
