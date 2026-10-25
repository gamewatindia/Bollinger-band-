# Shark Exchange – Bollinger Squeeze Breakout Backtest

Strategy
- Bollinger Bands (20, 2σ). **Squeeze** = bandwidth pichli 120 candles ke bottom 20% me, kam se kam 6 candles lagatar.
- `mode: mtf` -> base TF (15m) par breakout tab valid jab confluence TFs (1h, 4h) me bhi squeeze ho. `mode: single` -> har TF alag.
- Entry: candle close upper band ke upar = LONG, lower band ke neeche = SHORT; entry agli candle ke open par.
- Exit (partial TP): TP1 +1% par 25% qty book -> SL TP1 par; TP2 +2% par 50% book -> SL TP2 par; TP3 +5% par bachi 25% book. Initial SL = signal candle ki BB middle line. (% = price move; 10x par 1% = 10% margin.)
- Size: Rs 1000 margin x 10x = Rs 10,000 notional. 1% price move = Rs 100.
- Ek symbol/TF par ek time me ek hi position. Same candle me SL aur TP dono lage to SL pehle maana jaata hai; SL shift agli candle se lagu hota hai.

## Run
    pip install -r requirements.txt
    python run_backtest.py --source gate --symbols BTCUSDT,ETHUSDT --days 365   # pehle chhota test
    # --source gate | mexc | bybit | weex | csv
    python run_backtest.py                                         # saare USDT perpetual pairs
Output `results/`: `summary.csv`, `per_symbol.csv`, `exit_reasons.csv`, `trades.csv`, `equity.png`.
Tests: `PYTHONPATH=. python tests/test_all.py`

## Important limits
- Shark Exchange ka **public API / historical data mujhe nahi mila**. Data Gate / MEXC / Bybit / Weex ke USDT perpetual candles se aata hai (Binance nahi). Gate, MEXC, Bybit adapters ke endpoints docs ke hisaab se likhe hain par yahan live test nahi ho paaye; Weex adapter **unverified** hai. Pehle 2 symbols par chala ke dekho; fail ho to `--source csv`.
- `symbols: all` us exchange ke pairs deta hai, Shark ke nahi — Shark ke pairs `symbols.txt` me daalo (config me `symbols: symbols.txt`).
- Fees/slippage config ke estimates hain; funding rate, liquidation engine aur order-book slippage model nahi hain. Backtest result future profit ki guarantee nahi.
- `tools/make_synthetic.py` sirf offline smoke-test ke liye hai (random data, koi real result nahi).
