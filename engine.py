import numpy as np


def simulate(df, sig, t):
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
        side, e, sl0 = int(sig[i]), o[i + 1], mid[i]
        if (side == 1 and sl0 >= e) or (side == -1 and sl0 <= e) or abs(e - sl0) / e > t["max_sl_pct"] / 100:
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
