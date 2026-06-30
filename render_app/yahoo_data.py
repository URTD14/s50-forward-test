from datetime import datetime, timezone
import httpx

TF_MS = {'1m': 60000, '5m': 300000, '15m': 900000}
TF_INTERVALS = {'1m': '1m', '5m': '5m', '15m': '15m'}
TF_RANGES = {'1m': '5d', '5m': '1mo', '15m': '1mo'}


async def fetch_bars(tf: str) -> list[dict]:
    interval = TF_INTERVALS.get(tf, '15m')
    rng = TF_RANGES.get(tf, '1mo')
    tf_ms = TF_MS.get(tf, 900000)
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/IDEA.NS?interval={interval}&range={rng}'

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })

    if resp.status_code != 200:
        raise RuntimeError(f'Yahoo Finance API error: {resp.status_code} {resp.reason_phrase}')

    data = resp.json()
    result = data.get('chart', {}).get('result', [None])[0]
    if not result:
        return []

    timestamps = result.get('timestamp', [])
    quotes = result.get('indicators', {}).get('quote', [{}])[0]
    if not timestamps or not quotes:
        return []

    bars = []
    for i, ts in enumerate(timestamps):
        try:
            o = quotes['open'][i]
            h = quotes['high'][i]
            l = quotes['low'][i]
            c = quotes['close'][i]
            v = quotes['volume'][i]
        except (IndexError, TypeError):
            continue
        if None in (o, h, l, c, v):
            continue
        bars.append({
            'date': datetime.fromtimestamp(ts, tz=timezone.utc),
            'open': float(o),
            'high': float(h),
            'low': float(l),
            'close': float(c),
            'volume': int(v),
        })

    cutoff = datetime.now(timezone.utc).timestamp() * 1000 - 15 * 60 * 1000
    return [b for b in bars if b['date'].timestamp() * 1000 + tf_ms <= cutoff]
