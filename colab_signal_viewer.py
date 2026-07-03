# S50 Forward Test — Standalone Signal Viewer (yfinance only)
# Paste into Colab and run.
# For Colab: uncomment the line below
# !pip install yfinance pandas -q

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
import warnings
warnings.filterwarnings('ignore')

SYMBOL = "IDEA.NS"
SKIP = 20  # skip first N bars for volume average to warm up

def compute_pdh_pdl(bars):
    pdh = max(b['High'] for b in bars)
    pdl = min(b['Low'] for b in bars)
    return {'pdh': pdh, 'pdl': pdl, 'pdr': pdh - pdl}

def compute_vwap(bars_df):
    tp = (bars_df['High'] + bars_df['Low'] + bars_df['Close']) / 3
    cum_tpv = (tp * bars_df['Volume']).cumsum()
    cum_vol = bars_df['Volume'].cumsum()
    return (cum_tpv / cum_vol).tolist()

def compute_vol_avg(bars_df, period=SKIP):
    return bars_df['Volume'].rolling(period).mean().fillna(0).tolist()

def check_signal(bar, pdh, pdl, pdr, vwap, vol_avg):
    if vol_avg <= 0:
        return None
    if bar['High'] > pdh and bar['Close'] > vwap and bar['Volume'] >= 1.5 * vol_avg:
        return {'direction': 'BUY', 'entry': round(pdh, 2),
                'sl': round(pdh - 0.75*pdr, 2), 'tp': round(pdh + 0.75*pdr, 2)}
    if bar['Low'] < pdl and bar['Close'] < vwap and bar['Volume'] >= 1.5 * vol_avg:
        return {'direction': 'SELL', 'entry': round(pdl, 2),
                'sl': round(pdl + 0.75*pdr, 2), 'tp': round(pdl - 0.75*pdr, 2)}
    return None

# --- fetch ---
end = datetime.now(timezone.utc) - timedelta(minutes=15)
start = end - timedelta(days=5)
today_label = datetime.now(timezone.utc).strftime('%d %b %Y')

print(f"\n  S50 signals for {SYMBOL} — {today_label}")
print(f"  {'='*45}\n")

for interval, name in [('1m','1m'), ('5m','5m'), ('15m','15m')]:
    df = yf.download(SYMBOL, interval=interval, start=start, end=end,
                     progress=False, auto_adjust=True)
    if df.empty:
        print(f"  {name}: No data\n"); continue

    # flatten MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    # split by date
    by_date = {k: v for k, v in df.groupby(df.index.date)}
    dates = sorted(by_date.keys())
    if len(dates) < 2:
        print(f"  {name}: Need ≥2 trading days\n"); continue

    today, prev = dates[-1], dates[-2]
    today_bars = by_date[today]
    prev_bars = by_date[prev]

    # compute
    pdh_pdl = compute_pdh_pdl(prev_bars.to_dict('records'))
    vwaps = compute_vwap(today_bars)
    vol_avgs = compute_vol_avg(today_bars)

    print(f"  [{name}]  PDH={pdh_pdl['pdh']:.2f}  PDL={pdh_pdl['pdl']:.2f}  PDR={pdh_pdl['pdr']:.2f}")

    signals = []
    for i, (idx, row) in enumerate(today_bars.iterrows()):
        if i < SKIP or i >= len(vwaps) or i >= len(vol_avgs):
            continue
        sig = check_signal(row.to_dict(), pdh_pdl['pdh'], pdh_pdl['pdl'],
                           pdh_pdl['pdr'], vwaps[i], vol_avgs[i])
        if sig:
            sig['Time'] = idx.strftime('%H:%M')
            sig['Close'] = round(row['Close'], 2)
            sig['Vol'] = int(row['Volume'])
            signals.append(sig)

    print(f"  {len(signals)} signal(s)")
    if signals:
        cols = ['Time','direction','entry','sl','tp']
        print(pd.DataFrame(signals)[cols].rename(columns={
            'direction':'Dir','entry':'Entry','sl':'SL','tp':'TP'
        }).to_string(index=False))
    print()
