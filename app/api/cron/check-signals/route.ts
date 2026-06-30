import { NextRequest, NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { fetchBars } from '@/lib/yahoo'
import type { SignalResult } from '@/lib/strategy'
import {
  computePDHPDL,
  computeVWAP,
  computeVolumeAvg,
  checkSignal,
  zerodhaCost,
  groupBarsByDate,
} from '@/lib/strategy'

const CAPITAL = 15000
const MAX_TRADES_PER_DAY = 10
const CUTOFF_UTC_MINUTES = 9 * 60 + 45 // 15:15 IST = 09:45 UTC
const TF_MS: Record<string, number> = { '1m': 60000, '5m': 300000, '15m': 900000 }
const SKIP_FIRST_N_BARS = 20

export async function GET(request: NextRequest) {
  const startTime = Date.now()
  const tf = request.nextUrl.searchParams.get('tf') || '15m'

  if (!['1m', '5m', '15m'].includes(tf)) {
    return NextResponse.json({ error: `Invalid timeframe: ${tf}` }, { status: 400 })
  }

  try {
    const supabase = getSupabase()

    const allBars = await fetchBars(tf)
    if (allBars.length === 0) {
      return NextResponse.json({ error: 'No data from yfinance', signalsCreated: 0, positionsClosed: 0 })
    }

    const barsByDate = groupBarsByDate(allBars)
    const dateKeys = [...barsByDate.keys()].sort()

    if (dateKeys.length < 2) {
      return NextResponse.json({ error: 'Need at least 2 trading days of data', signalsCreated: 0, positionsClosed: 0 })
    }

    const volAvgs = computeVolumeAvg(allBars, 20)

    const vwapByDay = new Map<string, number[]>()
    const pdhPdlByDay = new Map<string, { pdh: number; pdl: number; pdr: number }>()

    for (let d = 0; d < dateKeys.length; d++) {
      const dayBars = barsByDate.get(dateKeys[d])!
      vwapByDay.set(dateKeys[d], computeVWAP(dayBars))

      if (d > 0) {
        const prevBars = barsByDate.get(dateKeys[d - 1])!
        pdhPdlByDay.set(dateKeys[d], computePDHPDL(prevBars))
      }
    }

    const now = new Date()
    const utcMinutes = now.getUTCHours() * 60 + now.getUTCMinutes()
    const isPastCutoff = utcMinutes >= CUTOFF_UTC_MINUTES

    const todayStart = new Date(now)
    todayStart.setUTCHours(0, 0, 0, 0)
    const todayEnd = new Date(now)
    todayEnd.setUTCHours(23, 59, 59, 999)

    const { count: todayTradesCount, error: todayCountErr } = await supabase
      .from('trades')
      .select('*', { count: 'exact', head: true })
      .gte('entered_at', todayStart.toISOString())
      .lte('entered_at', todayEnd.toISOString())

    if (todayCountErr) {
      return NextResponse.json({ error: todayCountErr.message }, { status: 500 })
    }

    const { count: openCount } = await supabase
      .from('open_positions')
      .select('*', { count: 'exact', head: true })

    const totalTradesToday = (todayTradesCount || 0) + (openCount || 0)

    const newSignals: Array<{
      signal: SignalResult
      signalDateKey: string
    }> = []

    for (let d = 1; d < dateKeys.length; d++) {
      const currDateKey = dateKeys[d]
      const pdhPdl = pdhPdlByDay.get(currDateKey)
      if (!pdhPdl) continue

      const currBars = barsByDate.get(currDateKey)!
      const vwaps = vwapByDay.get(currDateKey)!
      if (!vwaps) continue

      for (let i = SKIP_FIRST_N_BARS; i < currBars.length; i++) {
        const bar = currBars[i]
        const globalIdx = allBars.indexOf(bar)
        if (globalIdx < 0 || globalIdx >= volAvgs.length) continue

        const volAvg = volAvgs[globalIdx]
        if (volAvg <= 0) continue

        const barUtcMinutes = bar.date.getUTCHours() * 60 + bar.date.getUTCMinutes()
        if (barUtcMinutes >= CUTOFF_UTC_MINUTES) continue

        const sig = checkSignal(bar, pdhPdl.pdh, pdhPdl.pdl, pdhPdl.pdr, vwaps[i], volAvg)
        if (!sig) continue

        if (totalTradesToday + newSignals.length >= MAX_TRADES_PER_DAY) {
          continue
        }

        const { data: existing } = await supabase
          .from('signals')
          .select('id')
          .eq('timeframe', tf)
          .eq('bar_time', bar.date.toISOString())
          .eq('direction', sig.direction)
          .maybeSingle()

        if (existing) continue

        newSignals.push({ signal: sig, signalDateKey: currDateKey })
      }
    }

    let signalsCreated = 0
    for (const { signal: sig, signalDateKey } of newSignals) {
      const qty = Math.max(1, Math.floor(CAPITAL / sig.entry))
      const now = new Date()

      const { data: sigData, error: sigErr } = await supabase
        .from('signals')
        .insert({
          timeframe: tf,
          trade_date: signalDateKey,
          direction: sig.direction,
          bar_time: sig.barTime.toISOString(),
          entry_price: sig.entry,
          sl_price: sig.sl,
          tp_price: sig.tp,
          pdh: sig.pdh,
          pdl: sig.pdl,
          pdr: sig.pdr,
          vwap: sig.vwap,
          volume: sig.volume,
          vol_avg: sig.volAvg,
          status: 'active',
        })
        .select('id')
        .single()

      if (sigErr || !sigData) {
        continue
      }

      const { error: posErr } = await supabase
        .from('open_positions')
        .insert({
          signal_id: sigData.id,
          timeframe: tf,
          trade_date: signalDateKey,
          direction: sig.direction,
          entry_price: sig.entry,
          sl_price: sig.sl,
          tp_price: sig.tp,
          quantity: qty,
          entered_at: now.toISOString(),
        })

      if (!posErr) {
        signalsCreated++
      }
    }

    const { data: openPositions, error: posFetchErr } = await supabase
      .from('open_positions')
      .select('*')
      .eq('timeframe', tf)

    if (posFetchErr) {
      return NextResponse.json({ error: posFetchErr.message, signalsCreated, positionsClosed: 0 }, { status: 500 })
    }

    let positionsClosed = 0
    const closedDetails: Array<{ id: number; reason: string; pnl: number }> = []

    if (openPositions && openPositions.length > 0) {
      const signalIds = openPositions.map(p => p.signal_id)
      const { data: signalsMeta } = await supabase
        .from('signals')
        .select('id, bar_time')
        .in('id', signalIds)

      const signalBarMap = new Map<number, string>()
      for (const sm of signalsMeta || []) {
        signalBarMap.set(sm.id, sm.bar_time)
      }

      for (const pos of openPositions) {
        const barTimeStr = signalBarMap.get(pos.signal_id)
        if (!barTimeStr) continue

        const signalBarTime = new Date(barTimeStr)
        const barsAfter = allBars.filter(b => b.date.getTime() > signalBarTime.getTime())

        let hit: { price: number; reason: 'sl_hit' | 'tp_hit' | 'cutoff' } | null = null

        for (const bar of barsAfter) {
          if (pos.direction === 'BUY') {
            if (bar.low <= Number(pos.sl_price)) {
              hit = { price: Number(pos.sl_price), reason: 'sl_hit' }
              break
            }
            if (bar.high >= Number(pos.tp_price)) {
              hit = { price: Number(pos.tp_price), reason: 'tp_hit' }
              break
            }
          } else {
            if (bar.high >= Number(pos.sl_price)) {
              hit = { price: Number(pos.sl_price), reason: 'sl_hit' }
              break
            }
            if (bar.low <= Number(pos.tp_price)) {
              hit = { price: Number(pos.tp_price), reason: 'tp_hit' }
              break
            }
          }
        }

        if (!hit && isPastCutoff) {
          const lastBar = allBars[allBars.length - 1]
          if (lastBar) {
            hit = { price: lastBar.close, reason: 'cutoff' }
          }
        }

        if (hit) {
          const qty = Number(pos.quantity)
          const entry = Number(pos.entry_price)
          const exit = hit.price

          const grossPnl = pos.direction === 'BUY'
            ? qty * (exit - entry)
            : qty * (entry - exit)

          const costs = zerodhaCost(qty, entry, exit, pos.direction as 'BUY' | 'SELL')
          const netPnl = grossPnl - costs.total

          const tradeDate = pos.trade_date || new Date(pos.entered_at).toISOString().slice(0, 10)
          const { error: tradeErr } = await supabase
            .from('trades')
            .insert({
              signal_id: pos.signal_id,
              timeframe: pos.timeframe,
              trade_date: tradeDate,
              direction: pos.direction,
              entry_price: entry,
              exit_price: exit,
              sl_price: Number(pos.sl_price),
              tp_price: Number(pos.tp_price),
              quantity: qty,
              pnl: grossPnl,
              brokerage: costs.brokerage,
              stt: costs.stt,
              exchange_charges: costs.exchangeCharges,
              sebi_charges: costs.sebiCharges,
              gst: costs.gst,
              stamp_duty: costs.stampDuty,
              total_costs: costs.total,
              net_pnl: netPnl,
              exit_reason: hit.reason,
              entered_at: pos.entered_at,
              exited_at: new Date().toISOString(),
            })

          if (tradeErr) continue

          await supabase
            .from('signals')
            .update({
              status: 'closed',
              exit_price: exit,
              pnl: grossPnl,
              costs: costs.total,
              net_pnl: netPnl,
              exit_reason: hit.reason,
              closed_at: new Date().toISOString(),
            })
            .eq('id', pos.signal_id)

          await supabase
            .from('open_positions')
            .delete()
            .eq('id', pos.id)

          positionsClosed++
          closedDetails.push({ id: pos.id, reason: hit.reason, pnl: Math.round(netPnl * 100) / 100 })
        }
      }
    }

    const elapsed = Date.now() - startTime

    return NextResponse.json({
      timeframe: tf,
      elapsedMs: elapsed,
      signalsCreated,
      positionsClosed,
      closedDetails,
      openRemaining: (openPositions?.length || 0) - positionsClosed,
      barsProcessed: allBars.length,
      pastCutoff: isPastCutoff,
      totalTradesToday,
    })
  } catch (err: any) {
    return NextResponse.json({ error: err.message, signalsCreated: 0, positionsClosed: 0 }, { status: 500 })
  }
}
