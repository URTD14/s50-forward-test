from collections import defaultdict
from datetime import datetime, timezone


def compute_pdh_pdl(bars: list[dict]) -> dict:
    pdh = max(b['high'] for b in bars)
    pdl = min(b['low'] for b in bars)
    return {'pdh': pdh, 'pdl': pdl, 'pdr': pdh - pdl}


def compute_vwap(bars: list[dict]) -> list[float]:
    result = []
    cum_tpv = 0.0
    cum_vol = 0
    for b in bars:
        tp = (b['high'] + b['low'] + b['close']) / 3
        cum_tpv += tp * b['volume']
        cum_vol += b['volume']
        result.append(cum_tpv / cum_vol if cum_vol > 0 else b['close'])
    return result


def compute_volume_avg(bars: list[dict], period: int = 20) -> list[float]:
    result = []
    for i in range(len(bars)):
        if i < period:
            result.append(0.0)
        else:
            total = sum(bars[j]['volume'] for j in range(i - period, i))
            result.append(total / period)
    return result


def check_signal(bar: dict, pdh: float, pdl: float, pdr: float,
                 vwap: float, vol_avg: float) -> dict | None:
    if vol_avg <= 0:
        return None
    if bar['high'] > pdh and bar['close'] > vwap and bar['volume'] >= 1.5 * vol_avg:
        return {
            'direction': 'BUY',
            'entry': pdh,
            'sl': pdh - 0.75 * pdr,
            'tp': pdh + 0.75 * pdr,
        }
    if bar['low'] < pdl and bar['close'] < vwap and bar['volume'] >= 1.5 * vol_avg:
        return {
            'direction': 'SELL',
            'entry': pdl,
            'sl': pdl + 0.75 * pdr,
            'tp': pdl - 0.75 * pdr,
        }
    return None


def zerodha_cost(qty: int, entry: float, exit: float) -> dict:
    turnover_buy = qty * entry
    turnover_sell = qty * exit
    total_to = turnover_buy + turnover_sell
    brokerage = min(0.0003 * turnover_buy, 20) + min(0.0003 * turnover_sell, 20)
    stt = 0.00025 * turnover_sell
    exchange_charges = 0.0000325 * total_to
    sebi = 0.000001 * total_to
    gst = 0.18 * (brokerage + exchange_charges)
    stamp_duty = 0.00015 * turnover_buy
    total = brokerage + stt + exchange_charges + sebi + gst + stamp_duty
    return {
        'brokerage': round(brokerage, 2),
        'stt': round(stt, 2),
        'exchange_charges': round(exchange_charges, 2),
        'sebi_charges': round(sebi, 2),
        'gst': round(gst, 2),
        'stamp_duty': round(stamp_duty, 2),
        'total': round(total, 2),
    }


def group_bars_by_date(bars: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for b in bars:
        key = b['date'].strftime('%Y-%m-%d')
        groups[key].append(b)
    return dict(groups)
