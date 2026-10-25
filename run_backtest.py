import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import yaml
from sharkbt.data import ADAPTERS, get_candles, list_symbols
from sharkbt.engine import simulate
from sharkbt.report import write_report
from sharkbt.strategy import add_bb, htf_flag, make_signals


def run_symbol(sym, cfg, refresh):
    bb, sq, t = cfg["bb"], cfg["squeeze"], cfg["trade"]
    prep = lambda tf: add_bb(get_candles(sym, tf, cfg, refresh), bb["period"], bb["std"],
                             sq["lookback"], sq["quantile"], sq["min_bars"])
    trades = []
    if cfg["mode"] == "mtf":
        base_tf = cfg["base_tf"]
        base = prep(base_tf)
        flags = [htf_flag(base, prep(tf), tf) for tf in cfg["confluence_tfs"] if tf != base_tf]
        jobs = [(base_tf, base, make_signals(base, flags))]
    else:
        jobs = []
        for tf in cfg["single_tfs"]:
            d = prep(tf)
            jobs.append((tf, d, make_signals(d, [])))
    for tf, d, sig in jobs:
        for tr in simulate(d, sig, t):
            trades.append(dict(symbol=sym, tf=tf, **tr))
    return trades


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
