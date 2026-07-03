# S50 Forward Test — Signal Viewer for Colab
# Paste this entire cell into Google Colab and run.

# --- SETUP (run once) ---
!pip install supabase pandas tabulate -q

from supabase import create_client
import pandas as pd
from datetime import datetime, timezone, date
import warnings
warnings.filterwarnings('ignore')

# --- FILL THESE IN ---
SUPABASE_URL = "https://roxiyshdxpymmcnsiqpz.supabase.co"
SUPABASE_ANON_KEY = "PASTE_YOUR_ANON_KEY_HERE"  # Get from Supabase → Settings → API → anon public

# --- FETCH ---
sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
today = date.today().isoformat()

resp = sb.table('signals').select('*').eq('trade_date', today).order('bar_time', desc=True).execute()
rows = resp.data

if not rows:
    print(f"\n  No signals for {today}")
else:
    df = pd.DataFrame(rows)

    # drop noisy internal cols if present
    for c in ['id', 'trade_date']:
        if c in df.columns: df.drop(columns=[c], inplace=True)

    # parse & format bar_time
    if 'bar_time' in df.columns:
        df['bar_time'] = pd.to_datetime(df['bar_time'])
        df['Time'] = df['bar_time'].dt.strftime('%H:%M')

    # pick display columns
    cols = ['Timeframe', 'Direction', 'Time', 'Entry', 'SL', 'TP',
            'PDH', 'PDL', 'PDR', 'VWAP', 'Volume', 'VolAvg', 'Status']
    rename = {
        'timeframe': 'Timeframe', 'direction': 'Direction',
        'entry_price': 'Entry', 'sl_price': 'SL', 'tp_price': 'TP',
        'pdh': 'PDH', 'pdl': 'PDL', 'pdr': 'PDR',
        'vwap': 'VWAP', 'volume': 'Volume', 'vol_avg': 'VolAvg', 'status': 'Status'
    }
    df.rename(columns=rename, inplace=True)
    display_cols = [c for c in cols if c in df.columns]
    disp = df[display_cols].copy()

    # numeric formatting
    for c in ['Entry','SL','TP','PDH','PDL','PDR','VWAP']:
        if c in disp.columns: disp[c] = disp[c].round(2)
    for c in ['Volume','VolAvg']:
        if c in disp.columns: disp[c] = disp[c].astype(int)

    # --- PRINT ---
    print(f"\n  S50 Signals — {today}  ({len(rows)} total)\n")
    for tf in ['1m','5m','15m']:
        sub = disp[disp['Timeframe'] == tf]
        if sub.empty:
            print(f"  {tf}: —")
        else:
            buys = len(sub[sub['Direction'] == 'BUY'])
            sells = len(sub[sub['Direction'] == 'SELL'])
            print(f"  {tf}: {len(sub)} signals  ({buys}B / {sells}S)")
            print(sub.to_string(index=False))
        print()

    # --- LAST 10 DETAILED ---
    print("  === Last 10 Signals ===\n")
    detail_cols = ['Timeframe','Direction','Time','Entry','SL','TP','Status']
    detail_cols = [c for c in detail_cols if c in disp.columns]
    print(disp[detail_cols].head(10).to_string(index=False))
