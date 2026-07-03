import os
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse

from .yahoo_data import fetch_bars
from .strategy import (
    compute_pdh_pdl, compute_vwap, compute_volume_avg,
    check_signal, zerodha_cost, group_bars_by_date,
)
from .supabase_db import get_db

app = FastAPI()

CAPITAL = 15000
MAX_TRADES_PER_DAY = 10
CUTOFF_UTC_MINUTES = 9 * 60 + 45  # 15:15 IST
NSE_OPEN_UTC = 3 * 60 + 45  # 09:15 IST
NSE_CLOSE_UTC = 10 * 60 + 0  # 15:30 IST
TF_MS = {'1m': 60000, '5m': 300000, '15m': 900000}
SKIP_FIRST_N_BARS = 20


def is_market_open() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return NSE_OPEN_UTC <= mins < NSE_CLOSE_UTC


async def _run_check(tf: str) -> dict:
    start = datetime.now()
    if not is_market_open():
        return {'error': 'Market closed', 'signalsCreated': 0, 'positionsClosed': 0}

    try:
        supabase = get_db()
    except RuntimeError as e:
        return {'error': f'Supabase: {e}', 'signalsCreated': 0, 'positionsClosed': 0}

    try:
        all_bars = await fetch_bars(tf)
    except Exception as e:
        return {'error': f'Yahoo: {e}', 'signalsCreated': 0, 'positionsClosed': 0}
    if not all_bars:
        return {'error': 'No data from yfinance', 'signalsCreated': 0, 'positionsClosed': 0}

    bars_by_date = group_bars_by_date(all_bars)
    date_keys = sorted(bars_by_date.keys())
    if len(date_keys) < 2:
        return {'error': 'Need at least 2 trading days', 'signalsCreated': 0, 'positionsClosed': 0}

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

    try:
        today_count_resp = supabase.table('trades').select('id', count='exact')\
            .gte('entered_at', today_start.isoformat())\
            .lte('entered_at', today_end.isoformat()).execute()
        today_trades_count = today_count_resp.count if today_count_resp else 0
    except Exception:
        today_trades_count = 0

    try:
        open_count_resp = supabase.table('open_positions').select('id', count='exact').execute()
        open_count = open_count_resp.count if open_count_resp else 0
    except Exception:
        open_count = 0
    total_trades_today = today_trades_count + open_count

    today_key = now.strftime('%Y-%m-%d')
    today_bars = bars_by_date.get(today_key)
    prev_key = date_keys[date_keys.index(today_key) - 1] if today_key in date_keys and date_keys.index(today_key) > 0 else None
    pdh_pdl_today = pdh_pdl_by_day.get(today_key) if prev_key else None

    new_signals = []
    if today_bars and pdh_pdl_today:
        vwaps_today = vwap_by_day.get(today_key, [])
        if vwaps_today:
            for i in range(SKIP_FIRST_N_BARS, len(today_bars)):
                bar = today_bars[i]
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
                sig = check_signal(bar, pdh_pdl_today['pdh'], pdh_pdl_today['pdl'], pdh_pdl_today['pdr'], vwaps_today[i], vol_avg)
                if not sig:
                    continue
                if total_trades_today + len(new_signals) >= MAX_TRADES_PER_DAY:
                    continue
                try:
                    existing = supabase.table('signals').select('id')\
                        .eq('timeframe', tf).eq('bar_time', bar['date'].isoformat())\
                        .eq('direction', sig['direction']).maybe_single().execute()
                    if existing and existing.data:
                        continue
                except Exception:
                    pass
                new_signals.append({'signal': sig, 'date_key': today_key, 'bar': bar,
                    'pdh_pdl': pdh_pdl_today, 'vwap_val': vwaps_today[i], 'vol_avg_val': vol_avg})

    signals_created = 0
    for ns in new_signals:
        sig = ns['signal']
        qty = max(1, int(CAPITAL / sig['entry']))
        now_iso = datetime.now(timezone.utc).isoformat()
        bar_time_iso = ns['bar']['date'].isoformat()

        try:
            sig_resp = supabase.table('signals').insert({
                'timeframe': tf, 'trade_date': ns['date_key'], 'direction': sig['direction'],
                'bar_time': bar_time_iso, 'entry_price': sig['entry'], 'sl_price': sig['sl'],
                'tp_price': sig['tp'], 'pdh': ns['pdh_pdl']['pdh'], 'pdl': ns['pdh_pdl']['pdl'],
                'pdr': ns['pdh_pdl']['pdr'], 'vwap': ns['vwap_val'], 'volume': ns['bar']['volume'],
                'vol_avg': ns['vol_avg_val'], 'status': 'active',
            }).execute()
        except Exception as e:
            continue

        if not sig_resp or not sig_resp.data or len(sig_resp.data) < 1:
            continue
        sig_id = sig_resp.data[0]['id']
        try:
            pos_resp = supabase.table('open_positions').insert({
                'signal_id': sig_id, 'timeframe': tf, 'trade_date': ns['date_key'],
                'direction': sig['direction'], 'entry_price': sig['entry'],
                'sl_price': sig['sl'], 'tp_price': sig['tp'], 'quantity': qty,
                'entered_at': now_iso,
            }).execute()
        except Exception:
            continue
        if pos_resp:
            signals_created += 1

    try:
        open_positions_resp = supabase.table('open_positions').select('*').eq('timeframe', tf).execute()
        open_positions = open_positions_resp.data if open_positions_resp else []
    except Exception:
        open_positions = []

    positions_closed = 0
    closed_details = []

    for pos in open_positions:
        try:
            signal_resp = supabase.table('signals').select('bar_time').eq('id', pos['signal_id']).maybe_single().execute()
            if not signal_resp or not signal_resp.data:
                continue
            signal_bar_time = datetime.fromisoformat(signal_resp.data['bar_time'])
        except Exception:
            continue
        bars_after = [b for b in all_bars if b['date'].timestamp() > signal_bar_time.timestamp()]

        hit = None
        for bar in bars_after:
            if pos['direction'] == 'BUY':
                if bar['low'] <= float(pos['sl_price']):
                    hit = {'price': float(pos['sl_price']), 'reason': 'sl_hit'}; break
                if bar['high'] >= float(pos['tp_price']):
                    hit = {'price': float(pos['tp_price']), 'reason': 'tp_hit'}; break
            else:
                if bar['high'] >= float(pos['sl_price']):
                    hit = {'price': float(pos['sl_price']), 'reason': 'sl_hit'}; break
                if bar['low'] <= float(pos['tp_price']):
                    hit = {'price': float(pos['tp_price']), 'reason': 'tp_hit'}; break

        if not hit and is_past_cutoff:
            last_bar = all_bars[-1] if all_bars else None
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

            try:
                supabase.table('trades').insert({
                    'signal_id': pos['signal_id'], 'timeframe': pos['timeframe'], 'trade_date': trade_date,
                    'direction': pos['direction'], 'entry_price': entry, 'exit_price': exit_price,
                    'sl_price': float(pos['sl_price']), 'tp_price': float(pos['tp_price']),
                    'quantity': qty, 'pnl': round(gross, 2), 'brokerage': costs['brokerage'],
                    'stt': costs['stt'], 'exchange_charges': costs['exchange_charges'],
                    'sebi_charges': costs['sebi_charges'], 'gst': costs['gst'],
                    'stamp_duty': costs['stamp_duty'], 'total_costs': costs['total'],
                    'net_pnl': round(net, 2), 'exit_reason': hit['reason'],
                    'entered_at': pos['entered_at'], 'exited_at': datetime.now(timezone.utc).isoformat(),
                }).execute()

                supabase.table('signals').update({
                    'status': 'closed', 'exit_price': exit_price, 'pnl': round(gross, 2),
                    'costs': costs['total'], 'net_pnl': round(net, 2), 'exit_reason': hit['reason'],
                    'closed_at': datetime.now(timezone.utc).isoformat(),
                }).eq('id', pos['signal_id']).execute()

                supabase.table('open_positions').delete().eq('id', pos['id']).execute()
            except Exception:
                pass

            positions_closed += 1
            closed_details.append({'id': pos['id'], 'reason': hit['reason'], 'pnl': round(net, 2)})

    elapsed = (datetime.now() - start).total_seconds() * 1000
    remaining = len(open_positions) - positions_closed

    return {
        'timeframe': tf, 'elapsedMs': int(elapsed),
        'signalsCreated': signals_created, 'positionsClosed': positions_closed,
        'closedDetails': closed_details, 'openRemaining': remaining,
        'barsProcessed': len(all_bars), 'pastCutoff': is_past_cutoff,
        'totalTradesToday': total_trades_today,
    }


@app.get('/api/cron/check-signals')
async def check_signals(request: Request):
    tf = request.query_params.get('tf', '15m')
    if tf not in TF_MS:
        return JSONResponse({'error': f'Invalid timeframe: {tf}'}, status_code=400)
    try:
        result = await _run_check(tf)
        if 'error' in result:
            return JSONResponse(result, status_code=500)
        return result
    except Exception as e:
        return JSONResponse({'error': str(e), 'signalsCreated': 0, 'positionsClosed': 0}, status_code=500)


@app.get('/api/export/signals.csv')
async def export_signals_csv():
    try:
        supabase = get_db()
    except RuntimeError:
        return JSONResponse({'error': 'Missing Supabase env vars'}, status_code=500)
    data = (supabase.table('signals').select('*').order('detected_at', desc=True).execute()).data or []
    if not data:
        return HTMLResponse('No data', status_code=404)
    cols = ['id','detected_at','trade_date','timeframe','bar_time','direction','entry_price','sl_price','tp_price','pdh','pdl','pdr','vwap','volume','vol_avg','status','exit_price','pnl','costs','net_pnl','exit_reason','closed_at']
    def esc(v): v = str(v); return f'"{v}"' if ',' in v or '"' in v else v
    lines = [','.join(cols)]
    for r in data:
        lines.append(','.join(esc(r.get(c,'')) for c in cols))
    return HTMLResponse('\n'.join(lines), headers={'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=signals.csv'})


@app.get('/api/export/trades.csv')
async def export_trades_csv():
    try:
        supabase = get_db()
    except RuntimeError:
        return JSONResponse({'error': 'Missing Supabase env vars'}, status_code=500)
    data = (supabase.table('trades').select('*').order('exited_at', desc=True).execute()).data or []
    if not data:
        return HTMLResponse('No data', status_code=404)
    cols = ['id','signal_id','timeframe','trade_date','direction','entry_price','exit_price','sl_price','tp_price','quantity','pnl','brokerage','stt','exchange_charges','sebi_charges','gst','stamp_duty','total_costs','net_pnl','exit_reason','entered_at','exited_at']
    def esc(v): v = str(v); return f'"{v}"' if ',' in v or '"' in v else v
    lines = [','.join(cols)]
    for r in data:
        lines.append(','.join(esc(r.get(c,'')) for c in cols))
    return HTMLResponse('\n'.join(lines), headers={'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=trades.csv'})


@app.get('/api/cron/check-all')
async def check_all():
    results = {}
    for tf in ['1m', '5m', '15m']:
        try:
            result = await _run_check(tf)
        except Exception as e:
            result = {'error': str(e), 'signalsCreated': 0, 'positionsClosed': 0}
        results[tf] = result
    return results


@app.get('/', response_class=HTMLResponse)
async def dashboard():
    try:
        supabase = get_db()
    except RuntimeError:
        return HTMLResponse('<h1>Missing Supabase env vars</h1>', status_code=500)

    trades = (supabase.table('trades').select('*').order('exited_at', desc=True).limit(100).execute()).data or []
    signals = (supabase.table('signals').select('*').order('detected_at', desc=True).limit(100).execute()).data or []
    open_pos = (supabase.table('open_positions').select('*').execute()).data or []

    total = len(trades)
    wins = sum(1 for t in trades if float(t['pnl']) > 0)
    gp = sum(float(t['pnl']) for t in trades)
    np = sum(float(t['net_pnl']) for t in trades)
    wr = round(wins / total * 100) if total else 0
    gw = sum(float(t['pnl']) for t in trades if float(t['pnl']) > 0)
    gl = abs(sum(float(t['pnl']) for t in trades if float(t['pnl']) < 0))
    pf = round(gw / gl, 2) if gl else (gw if gw else 0)

    def fmt(v):
        p = '+' if v >= 0 else ''
        return p + f'{v:,.2f}'

    pf_str = f'{pf:.2f}' if isinstance(pf, float) else str(pf)

    def r2(x):
        try: return f'{float(x):.2f}'
        except: return str(x)

    rows_tf = ''
    for tf in ['1m', '5m', '15m']:
        tt = [t for t in trades if t['timeframe'] == tf]
        tw = sum(1 for t in tt if float(t['pnl']) > 0)
        tl = len(tt) - tw
        tg = sum(float(t['pnl']) for t in tt)
        tn = sum(float(t['net_pnl']) for t in tt)
        ts = len([s for s in signals if s['timeframe'] == tf])
        twr = round(tw / len(tt) * 100) if tt else 0
        tgc = 'green' if tg >= 0 else 'red'
        tnc = 'green' if tn >= 0 else 'red'
        rows_tf += f'<tr><td><strong>{tf}</strong></td><td>{ts}</td><td>{len(tt)}</td>'
        rows_tf += f'<td class="green">{tw}</td><td class="red">{tl}</td>'
        rows_tf += f'<td class="{tgc}">{fmt(tg)}</td><td class="{tnc}">{fmt(tn)}</td><td>{twr}%</td></tr>'

    rows_open = ''
    for p in open_pos:
        rows_open += f'<tr><td>{p["entered_at"][:16]}</td><td>{p["timeframe"]}</td>'
        rows_open += f'<td><span class="badge {p["direction"].lower()}">{p["direction"]}</span></td>'
        rows_open += f'<td>{r2(p["entry_price"])}</td><td>{r2(p["sl_price"])}</td><td>{r2(p["tp_price"])}</td><td>{p["quantity"]}</td></tr>'

    rows_sig = ''
    for s in signals:
        vwap_str = f'{float(s["vwap"]):.2f}' if s.get('vwap') else '-'
        rows_sig += f'<tr><td>{s["bar_time"][:16]}</td><td>{s["timeframe"]}</td>'
        rows_sig += f'<td><span class="badge {s["direction"].lower()}">{s["direction"]}</span></td>'
        rows_sig += f'<td>{r2(s["entry_price"])}</td><td>{r2(s["sl_price"])}</td><td>{r2(s["tp_price"])}</td>'
        rows_sig += f'<td>{vwap_str}</td><td>{s["volume"]}</td>'
        rows_sig += f'<td><span class="badge {s["status"]}">{s["status"]}</span></td></tr>'

    rows_tr = ''
    for t in trades:
        pnl_c = 'green' if float(t['pnl']) >= 0 else 'red'
        net_c = 'green' if float(t['net_pnl']) >= 0 else 'red'
        rows_tr += f'<tr><td>{t["exited_at"][:16]}</td><td>{t["timeframe"]}</td>'
        rows_tr += f'<td><span class="badge {t["direction"].lower()}">{t["direction"]}</span></td>'
        rows_tr += f'<td>{r2(t["entry_price"])}</td><td>{r2(t["exit_price"])}</td><td>{t["quantity"]}</td>'
        rows_tr += f'<td class="{pnl_c}">{float(t["pnl"]):.2f}</td>'
        rows_tr += f'<td class="{net_c}">{float(t["net_pnl"]):.2f}</td>'
        rows_tr += f'<td>{t["exit_reason"]}</td></tr>'

    open_section = ''
    if open_pos:
        open_section = '<h2 class="st">Open Positions</h2><table><thead><tr>'
        open_section += '<th>Time</th><th>TF</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Qty</th></tr></thead><tbody>'
        open_section += rows_open + '</tbody></table>'
    else:
        open_section = '<h2 class="st">Open Positions</h2><p class="empty">No open positions</p>'

    sig_section = '<h2 class="st">Signals Log</h2>'
    if signals:
        sig_section += '<table><thead><tr><th>Time</th><th>TF</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>VWAP</th><th>Vol</th><th>Status</th></tr></thead><tbody>'
        sig_section += rows_sig + '</tbody></table>'
    else:
        sig_section += '<p class="empty">No signals yet</p>'

    trades_section = '<h2 class="st">Trade Log</h2>'
    if trades:
        trades_section += '<table><thead><tr><th>Exited</th><th>TF</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>Net</th><th>Why</th></tr></thead><tbody>'
        trades_section += rows_tr + '</tbody></table>'
    else:
        trades_section += '<p class="empty">No trades yet</p>'

    gpc = 'green' if gp >= 0 else 'red'
    npc = 'green' if np >= 0 else 'red'

    html = '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
    html += '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
    html += '<title>S50 Forward Test</title><style>'
    html += '*{margin:0;padding:0;box-sizing:border-box}'
    html += 'body{font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;background:#0f172a;color:#e2e8f0}'
    html += '.container{max-width:1200px;margin:0 auto;padding:20px}'
    html += 'h1{font-size:1.5rem;margin-bottom:8px;color:#f8fafc}'
    html += '.subtitle{color:#94a3b8;font-size:0.85rem;margin-bottom:24px}'
    html += '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}'
    html += '.card{background:#1e293b;border-radius:8px;padding:16px;border:1px solid #334155}'
    html += '.card .l{font-size:0.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em}'
    html += '.card .v{font-size:1.5rem;font-weight:700;margin-top:4px}'
    html += '.green{color:#22c55e}.red{color:#ef4444}.blue{color:#3b82f6}'
    html += '.tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid #334155}'
    html += '.tab{padding:10px 20px;cursor:pointer;border:none;background:none;color:#94a3b8;font-size:0.9rem;border-bottom:2px solid transparent}'
    html += '.tab.active{color:#3b82f6;border-bottom-color:#3b82f6}'
    html += 'table{width:100%;border-collapse:collapse;font-size:0.85rem}'
    html += 'th{text-align:left;padding:10px 8px;border-bottom:2px solid #334155;color:#94a3b8;font-weight:600;white-space:nowrap}'
    html += 'td{padding:8px;border-bottom:1px solid #1e293b;white-space:nowrap}'
    html += '.badge{padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600}'
    html += '.badge.buy{background:#166534;color:#86efac}'
    html += '.badge.sell{background:#7f1d1d;color:#fca5a5}'
    html += '.badge.active{background:#1e3a5f;color:#93c5fd}'
    html += '.badge.closed{background:#374151;color:#cbd5e1}'
    html += '.st{font-size:1.1rem;margin-bottom:12px;margin-top:24px;color:#f8fafc}'
    html += '.c{display:none}.c.active{display:block}'
    html += '.empty{color:#64748b;font-style:italic;padding:20px 0}'
    html += '</style></head><body><div class="container">'
    html += '<h1>S50 Forward Test</h1>'
    html += f'<p class="subtitle">IDEA.NS &middot; {total} trades &middot; {wr}% win rate &middot; {fmt(np)}</p>'
    html += '<div class="grid">'
    html += f'<div class="card"><div class="l">Gross P&amp;L</div><div class="v {gpc}">{fmt(gp)}</div></div>'
    html += f'<div class="card"><div class="l">Net P&amp;L</div><div class="v {npc}">{fmt(np)}</div></div>'
    html += f'<div class="card"><div class="l">Win Rate</div><div class="v blue">{wr}%</div></div>'
    html += f'<div class="card"><div class="l">Profit Factor</div><div class="v blue">{pf_str}</div></div>'
    html += f'<div class="card"><div class="l">Total Trades</div><div class="v blue">{total}</div></div>'
    html += f'<div class="card"><div class="l">Total Signals</div><div class="v blue">{len(signals)}</div></div>'
    html += '</div>'
    html += '<div class="tabs">'
    html += '<button class="tab active" onclick="st(\'d\')">Dashboard</button>'
    html += '<button class="tab" onclick="st(\'s\')">Signals</button>'
    html += '<button class="tab" onclick="st(\'t\')">Trades</button>'
    html += '</div>'
    html += '<div class="tabs-sections">'
    html += '<div id="d" class="c active">'
    html += '<h2 class="st">By Timeframe</h2>'
    html += '<table><thead><tr><th>TF</th><th>Sig</th><th>Tr</th><th>W</th><th>L</th><th>Gross</th><th>Net</th><th>WR</th></tr></thead><tbody>'
    html += rows_tf + '</tbody></table>'
    html += open_section + '</div>'
    html += '<div id="s" class="c">' + sig_section + '</div>'
    html += '<div id="t" class="c">' + trades_section + '</div>'
    html += '</div></div>'
    html += '<script>function st(i){document.querySelectorAll(\'.c\').forEach(e=>e.classList.remove(\'active\'));'
    html += 'document.querySelectorAll(\'.tab\').forEach(e=>e.classList.remove(\'active\'));'
    html += 'document.getElementById(i).classList.add(\'active\');event.target.classList.add(\'active\')}'
    html += '</script></body></html>'
    return HTMLResponse(html)
