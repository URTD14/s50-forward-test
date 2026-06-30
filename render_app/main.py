import os
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .yahoo_data import fetch_bars
from .strategy import (
    compute_pdh_pdl, compute_vwap, compute_volume_avg,
    check_signal, zerodha_cost, group_bars_by_date,
)
from .supabase_db import get_db

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / 'templates')

CAPITAL = 15000
MAX_TRADES_PER_DAY = 10
CUTOFF_UTC_MINUTES = 9 * 60 + 45
TF_MS = {'1m': 60000, '5m': 300000, '15m': 900000}
SKIP_FIRST_N_BARS = 20


@app.get('/api/cron/check-signals')
async def check_signals(request: Request):
    start = datetime.now()
    tf = request.query_params.get('tf', '15m')
    if tf not in TF_MS:
        return JSONResponse({'error': f'Invalid timeframe: {tf}'}, status_code=400)

    try:
        supabase = get_db()

        all_bars = await fetch_bars(tf)
        if not all_bars:
            return JSONResponse({'error': 'No data from yfinance', 'signalsCreated': 0, 'positionsClosed': 0})

        bars_by_date = group_bars_by_date(all_bars)
        date_keys = sorted(bars_by_date.keys())
        if len(date_keys) < 2:
            return JSONResponse({'error': 'Need at least 2 trading days', 'signalsCreated': 0, 'positionsClosed': 0})

        vol_avgs = compute_volume_avg(all_bars, 20)

        vwap_by_day = {}
        pdh_pdl_by_day = {}
        for d, dk in enumerate(date_keys):
            day_bars = bars_by_date[dk]
            vwap_by_day[dk] = compute_vwap(day_bars)
            if d > 0:
                prev_bars = bars_by_date[date_keys[d - 1]]
                pdh_pdl_by_day[dk] = compute_pdh_pdl(prev_bars)

        now = datetime.now(timezone.utc)
        utc_minutes = now.hour * 60 + now.minute
        is_past_cutoff = utc_minutes >= CUTOFF_UTC_MINUTES

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)

        today_count_resp = supabase.table('trades') \
            .select('id', count='exact') \
            .gte('entered_at', today_start.isoformat()) \
            .lte('entered_at', today_end.isoformat()) \
            .execute()
        today_trades_count = today_count_resp.count or 0

        open_count_resp = supabase.table('open_positions') \
            .select('id', count='exact') \
            .execute()
        open_count = open_count_resp.count or 0

        total_trades_today = today_trades_count + open_count

        new_signals = []
        for d in range(1, len(date_keys)):
            curr_dk = date_keys[d]
            pdh_pdl = pdh_pdl_by_day.get(curr_dk)
            if not pdh_pdl:
                continue

            curr_bars = bars_by_date[curr_dk]
            vwaps = vwap_by_day.get(curr_dk, [])
            if not vwaps:
                continue

            for i in range(SKIP_FIRST_N_BARS, len(curr_bars)):
                bar = curr_bars[i]
                try:
                    global_idx = all_bars.index(bar)
                except ValueError:
                    continue
                if global_idx >= len(vol_avgs):
                    continue

                vol_avg = vol_avgs[global_idx]
                if vol_avg <= 0:
                    continue

                bar_utc = bar['date'].hour * 60 + bar['date'].minute
                if bar_utc >= CUTOFF_UTC_MINUTES:
                    continue

                sig = check_signal(bar, pdh_pdl['pdh'], pdh_pdl['pdl'], pdh_pdl['pdr'], vwaps[i], vol_avg)
                if not sig:
                    continue

                if total_trades_today + len(new_signals) >= MAX_TRADES_PER_DAY:
                    continue

                existing = supabase.table('signals') \
                    .select('id') \
                    .eq('timeframe', tf) \
                    .eq('bar_time', bar['date'].isoformat()) \
                    .eq('direction', sig['direction']) \
                    .maybe_single() \
                    .execute()

                if existing.data:
                    continue

                new_signals.append({'signal': sig, 'date_key': curr_dk, 'bar': bar, 'pdh_pdl': pdh_pdl, 'vwap_val': vwaps[i], 'vol_avg_val': vol_avg})

        signals_created = 0
        for ns in new_signals:
            sig = ns['signal']
            qty = max(1, int(CAPITAL / sig['entry']))
            now_iso = datetime.now(timezone.utc).isoformat()
            bar_time_iso = ns['bar']['date'].isoformat()

            sig_resp = supabase.table('signals') \
                .insert({
                    'timeframe': tf,
                    'trade_date': ns['date_key'],
                    'direction': sig['direction'],
                    'bar_time': bar_time_iso,
                    'entry_price': sig['entry'],
                    'sl_price': sig['sl'],
                    'tp_price': sig['tp'],
                    'pdh': ns['pdh_pdl']['pdh'],
                    'pdl': ns['pdh_pdl']['pdl'],
                    'pdr': ns['pdh_pdl']['pdr'],
                    'vwap': ns['vwap_val'],
                    'volume': ns['bar']['volume'],
                    'vol_avg': ns['vol_avg_val'],
                    'status': 'active',
                }) \
                .execute()

            if not sig_resp.data:
                continue

            sig_id = sig_resp.data[0]['id']
            pos_resp = supabase.table('open_positions') \
                .insert({
                    'signal_id': sig_id,
                    'timeframe': tf,
                    'trade_date': ns['date_key'],
                    'direction': sig['direction'],
                    'entry_price': sig['entry'],
                    'sl_price': sig['sl'],
                    'tp_price': sig['tp'],
                    'quantity': qty,
                    'entered_at': now_iso,
                }) \
                .execute()

            if not pos_resp.error:
                signals_created += 1

        open_positions_resp = supabase.table('open_positions') \
            .select('*') \
            .eq('timeframe', tf) \
            .execute()
        open_positions = open_positions_resp.data or []

        positions_closed = 0
        closed_details = []

        for pos in open_positions:
            signal_resp = supabase.table('signals') \
                .select('bar_time') \
                .eq('id', pos['signal_id']) \
                .maybe_single() \
                .execute()
            if not signal_resp.data:
                continue

            signal_bar_time = datetime.fromisoformat(signal_resp.data['bar_time'])
            bars_after = [b for b in all_bars if b['date'].timestamp() > signal_bar_time.timestamp()]

            hit = None
            for bar in bars_after:
                if pos['direction'] == 'BUY':
                    if bar['low'] <= float(pos['sl_price']):
                        hit = {'price': float(pos['sl_price']), 'reason': 'sl_hit'}
                        break
                    if bar['high'] >= float(pos['tp_price']):
                        hit = {'price': float(pos['tp_price']), 'reason': 'tp_hit'}
                        break
                else:
                    if bar['high'] >= float(pos['sl_price']):
                        hit = {'price': float(pos['sl_price']), 'reason': 'sl_hit'}
                        break
                    if bar['low'] <= float(pos['tp_price']):
                        hit = {'price': float(pos['tp_price']), 'reason': 'tp_hit'}
                        break

            if not hit and is_past_cutoff:
                last_bar = all_bars[-1]
                if last_bar:
                    hit = {'price': last_bar['close'], 'reason': 'cutoff'}

            if hit:
                qty = int(pos['quantity'])
                entry = float(pos['entry_price'])
                exit_price = hit['price']
                gross = qty * (exit_price - entry) if pos['direction'] == 'BUY' else qty * (entry - exit_price)
                costs = zerodha_cost(qty, entry, exit_price)
                net = gross - costs['total']
                trade_date = pos.get('trade_date', pos['entered_at'][:10])

                supabase.table('trades') \
                    .insert({
                        'signal_id': pos['signal_id'],
                        'timeframe': pos['timeframe'],
                        'trade_date': trade_date,
                        'direction': pos['direction'],
                        'entry_price': entry,
                        'exit_price': exit_price,
                        'sl_price': float(pos['sl_price']),
                        'tp_price': float(pos['tp_price']),
                        'quantity': qty,
                        'pnl': round(gross, 2),
                        'brokerage': costs['brokerage'],
                        'stt': costs['stt'],
                        'exchange_charges': costs['exchange_charges'],
                        'sebi_charges': costs['sebi_charges'],
                        'gst': costs['gst'],
                        'stamp_duty': costs['stamp_duty'],
                        'total_costs': costs['total'],
                        'net_pnl': round(net, 2),
                        'exit_reason': hit['reason'],
                        'entered_at': pos['entered_at'],
                        'exited_at': datetime.now(timezone.utc).isoformat(),
                    }) \
                    .execute()

                supabase.table('signals') \
                    .update({
                        'status': 'closed',
                        'exit_price': exit_price,
                        'pnl': round(gross, 2),
                        'costs': costs['total'],
                        'net_pnl': round(net, 2),
                        'exit_reason': hit['reason'],
                        'closed_at': datetime.now(timezone.utc).isoformat(),
                    }) \
                    .eq('id', pos['signal_id']) \
                    .execute()

                supabase.table('open_positions') \
                    .delete() \
                    .eq('id', pos['id']) \
                    .execute()

                positions_closed += 1
                closed_details.append({'id': pos['id'], 'reason': hit['reason'], 'pnl': round(net, 2)})

        elapsed = (datetime.now() - start).total_seconds() * 1000
        remaining = len(open_positions) - positions_closed

        return {
            'timeframe': tf,
            'elapsedMs': int(elapsed),
            'signalsCreated': signals_created,
            'positionsClosed': positions_closed,
            'closedDetails': closed_details,
            'openRemaining': remaining,
            'barsProcessed': len(all_bars),
            'pastCutoff': is_past_cutoff,
            'totalTradesToday': total_trades_today,
        }

    except Exception as e:
        return JSONResponse({'error': str(e), 'signalsCreated': 0, 'positionsClosed': 0}, status_code=500)


@app.get('/', response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        supabase = get_db()
    except RuntimeError:
        return HTMLResponse('<h1>Missing Supabase env vars</h1>', status_code=500)

    # Fetch data
    trades_resp = supabase.table('trades').select('*').order('exited_at', desc=True).limit(100).execute()
    signals_resp = supabase.table('signals').select('*').order('detected_at', desc=True).limit(100).execute()
    open_resp = supabase.table('open_positions').select('*').execute()

    trades = trades_resp.data or []
    signals = signals_resp.data or []
    open_positions = open_resp.data or []

    # Aggregate summary
    total_trades = len(trades)
    wins = sum(1 for t in trades if float(t['pnl']) > 0)
    losses = sum(1 for t in trades if float(t['pnl']) <= 0)
    gross_pnl = sum(float(t['pnl']) for t in trades)
    net_pnl = sum(float(t['net_pnl']) for t in trades)
    total_signals = len(signals)
    win_rate = round(wins / total_trades * 100) if total_trades > 0 else 0

    gross_wins = sum(float(t['pnl']) for t in trades if float(t['pnl']) > 0)
    gross_losses = abs(sum(float(t['pnl']) for t in trades if float(t['pnl']) < 0))
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (gross_wins if gross_wins > 0 else 0)

    def fmt(v):
        prefix = '+' if v >= 0 else ''
        return f'{prefix}{v:,.2f}'

    summary = {
        'total_trades': total_trades,
        'gross_pnl': gross_pnl,
        'gross_pnl_str': fmt(gross_pnl),
        'net_pnl': net_pnl,
        'net_pnl_str': fmt(net_pnl),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_signals': total_signals,
    }

    # By timeframe
    by_tf = {}
    for tf in ['1m', '5m', '15m']:
        tf_trades = [t for t in trades if t['timeframe'] == tf]
        tf_wins = sum(1 for t in tf_trades if float(t['pnl']) > 0)
        tf_losses = sum(1 for t in tf_trades if float(t['pnl']) <= 0)
        tf_gross = sum(float(t['pnl']) for t in tf_trades)
        tf_net = sum(float(t['net_pnl']) for t in tf_trades)
        by_tf[tf] = {
            'signals': len([s for s in signals if s['timeframe'] == tf]),
            'trades': len(tf_trades),
            'wins': tf_wins,
            'losses': tf_losses,
            'gross_pnl': tf_gross,
            'gross_pnl_str': fmt(tf_gross),
            'net_pnl': tf_net,
            'net_pnl_str': fmt(tf_net),
            'win_rate': round(tf_wins / len(tf_trades) * 100) if tf_trades else 0,
        }

    return templates.TemplateResponse('dashboard.html', {
        'request': request,
        'summary': summary,
        'by_tf': by_tf,
        'trades': trades,
        'signals': signals,
        'open_positions': open_positions,
    })
