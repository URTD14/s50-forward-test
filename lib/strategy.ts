export interface Bar {
  date: Date
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface PDHPDL {
  pdh: number
  pdl: number
  pdr: number
}

export interface SignalResult {
  direction: 'BUY' | 'SELL'
  entry: number
  sl: number
  tp: number
  barTime: Date
  pdh: number
  pdl: number
  pdr: number
  vwap: number
  volume: number
  volAvg: number
}

export interface CostBreakdown {
  brokerage: number
  stt: number
  exchangeCharges: number
  sebiCharges: number
  gst: number
  stampDuty: number
  total: number
}

export function computePDHPDL(bars: Bar[]): PDHPDL {
  let pdh = -Infinity
  let pdl = Infinity
  for (const b of bars) {
    if (b.high > pdh) pdh = b.high
    if (b.low < pdl) pdl = b.low
  }
  const pdr = pdh - pdl
  return { pdh, pdl, pdr }
}

export function computeVWAP(bars: Bar[]): number[] {
  const result: number[] = []
  let cumTPV = 0
  let cumVol = 0
  for (const b of bars) {
    const tp = (b.high + b.low + b.close) / 3
    cumTPV += tp * b.volume
    cumVol += b.volume
    result.push(cumVol > 0 ? cumTPV / cumVol : b.close)
  }
  return result
}

export function computeVolumeAvg(bars: Bar[], period: number = 20): number[] {
  const result: number[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i < period) {
      result.push(0)
    } else {
      let sum = 0
      for (let j = i - period; j < i; j++) {
        sum += bars[j].volume
      }
      result.push(sum / period)
    }
  }
  return result
}

export function checkSignal(
  bar: Bar,
  pdh: number,
  pdl: number,
  pdr: number,
  vwap: number,
  volAvg: number,
): SignalResult | null {
  if (volAvg <= 0) return null

  if (bar.high > pdh && bar.close > vwap && bar.volume >= 1.5 * volAvg) {
    return {
      direction: 'BUY',
      entry: pdh,
      sl: pdh - 0.75 * pdr,
      tp: pdh + 0.75 * pdr,
      barTime: bar.date,
      pdh,
      pdl,
      pdr,
      vwap,
      volume: bar.volume,
      volAvg,
    }
  }

  if (bar.low < pdl && bar.close < vwap && bar.volume >= 1.5 * volAvg) {
    return {
      direction: 'SELL',
      entry: pdl,
      sl: pdl + 0.75 * pdr,
      tp: pdl - 0.75 * pdr,
      barTime: bar.date,
      pdh,
      pdl,
      pdr,
      vwap,
      volume: bar.volume,
      volAvg,
    }
  }

  return null
}

export function zerodhaCost(
  qty: number,
  entry: number,
  exit: number,
  _direction: 'BUY' | 'SELL',
): CostBreakdown {
  const turnoverBuy = qty * entry
  const turnoverSell = qty * exit
  const totalTurnover = turnoverBuy + turnoverSell

  const brokerageBuy = Math.min(0.0003 * turnoverBuy, 20)
  const brokerageSell = Math.min(0.0003 * turnoverSell, 20)
  const brokerage = brokerageBuy + brokerageSell

  const stt = 0.00025 * turnoverSell

  const exchangeCharges = 0.0000325 * totalTurnover

  const sebiCharges = 0.000001 * totalTurnover

  const gstValue = 0.18 * (brokerage + exchangeCharges)

  const stampDuty = 0.00015 * turnoverBuy

  const total = brokerage + stt + exchangeCharges + sebiCharges + gstValue + stampDuty

  return {
    brokerage,
    stt,
    exchangeCharges,
    sebiCharges,
    gst: gstValue,
    stampDuty,
    total,
  }
}

export function formatDateKey(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export function groupBarsByDate(bars: Bar[]): Map<string, Bar[]> {
  const map = new Map<string, Bar[]>()
  for (const b of bars) {
    const key = formatDateKey(b.date)
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(b)
  }
  return map
}
