export interface Bar {
  date: Date
  open: number
  high: number
  low: number
  close: number
  volume: number
}

const TF_MS: Record<string, number> = {
  '1m': 60000,
  '5m': 300000,
  '15m': 900000,
}

const TF_INTERVALS: Record<string, string> = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
}

const TF_RANGES: Record<string, string> = {
  '1m': '7d',
  '5m': '2mo',
  '15m': '2mo',
}

export async function fetchBars(tf: string): Promise<Bar[]> {
  const interval = TF_INTERVALS[tf] || '15m'
  const range = TF_RANGES[tf] || '2mo'
  const tfMs = TF_MS[tf] || 900000

  const url = `https://query1.finance.yahoo.com/v8/finance/chart/IDEA.NS?interval=${interval}&range=${range}`

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Accept': 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`Yahoo Finance API error: ${response.status} ${response.statusText}`)
  }

  const json = await response.json()

  if (!json?.chart?.result?.[0]) {
    return []
  }

  const result = json.chart.result[0]
  const timestamps: number[] = result.timestamp || []
  const quotes = result.indicators?.quote?.[0]

  if (!quotes || timestamps.length === 0) {
    return []
  }

  const bars: Bar[] = []
  for (let i = 0; i < timestamps.length; i++) {
    const o = quotes.open?.[i]
    const h = quotes.high?.[i]
    const l = quotes.low?.[i]
    const c = quotes.close?.[i]
    const v = quotes.volume?.[i]

    if (o == null || h == null || l == null || c == null || v == null) continue

    bars.push({
      date: new Date(timestamps[i] * 1000),
      open: o,
      high: h,
      low: l,
      close: c,
      volume: v,
    })
  }

  const cutoff = Date.now() - 15 * 60 * 1000

  return bars.filter(b => b.date.getTime() + tfMs <= cutoff)
}
