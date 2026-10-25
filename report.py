from pathlib import Path
import numpy as np
import pandas as pd


def _stats(g):
    g = g.sort_values("exit_time")
    pnl = g.pnl_inr
    eq = pnl.cumsum()
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return pd.Series(dict(trades=len(g), win_rate_pct=round((pnl > 0).mean() * 100, 2),
                          tp1_hit_pct=round((g.tp_hits >= 1).mean() * 100, 1),
                          tp2_hit_pct=round((g.tp_hits >= 2).mean() * 100, 1),
                          tp3_hit_pct=round((g.tp_hits >= 3).mean() * 100, 1),
                          net_pnl_inr=round(pnl.sum(), 2), avg_trade_inr=round(pnl.mean(), 2),
                          profit_factor=round(gp / gl, 3) if gl > 0 else np.inf,
                          max_drawdown_inr=round((eq.cummax() - eq).max(), 2)))


def write_report(trades, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    if trades.empty:
        print("Koi trade nahi bana. Squeeze params ya symbols/days badlo.")
        return
    trades["entry_dt"] = pd.to_datetime(trades.entry_time, unit="ms")
    trades["exit_dt"] = pd.to_datetime(trades.exit_time, unit="ms")
    trades.to_csv(out / "trades.csv", index=False)
    summary = trades.groupby("tf").apply(_stats, include_groups=False).reset_index()
    summary.to_csv(out / "summary.csv", index=False)
    trades.groupby(["symbol", "tf"]).apply(_stats, include_groups=False).reset_index() \
        .to_csv(out / "per_symbol.csv", index=False)
    trades.groupby(["tf", "reason"]).pnl_inr.agg(["count", "sum"]).round(2).reset_index() \
        .to_csv(out / "exit_reasons.csv", index=False)
    print(summary.to_string(index=False))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        for tf, g in trades.groupby("tf"):
            g = g.sort_values("exit_time")
            ax.plot(g.exit_dt, g.pnl_inr.cumsum(), label=tf)
        ax.set_ylabel("Cumulative PnL (INR)"); ax.legend(); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / "equity.png", dpi=120)
    except Exception as ex:
        print("Plot skip:", ex)
