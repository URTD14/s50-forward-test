import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export async function GET() {
  try {
    const supabase = getSupabase()

    const { count: openCount } = await supabase
      .from('open_positions')
      .select('*', { count: 'exact', head: true })

    const { data: trades } = await supabase
      .from('trades')
      .select('net_pnl, pnl, direction, exited_at')
      .order('exited_at', { ascending: false })

    if (!trades) {
      return NextResponse.json({
        totalPnl: 0,
        grossPnl: 0,
        winRate: 0,
        profitFactor: 0,
        openPositions: openCount || 0,
        totalTrades: 0,
        dailyPnl: [],
        tradeStats: { wins: 0, losses: 0 },
      })
    }

    let grossPnl = 0
    let wins = 0
    let losses = 0
    let winSum = 0
    let lossSum = 0

    for (const t of trades) {
      const netPnl = Number(t.net_pnl)
      grossPnl += netPnl
      if (netPnl > 0) {
        wins++
        winSum += netPnl
      } else {
        losses++
        lossSum += Math.abs(netPnl)
      }
    }

    const totalTrades = trades.length
    const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
    const profitFactor = lossSum > 0 ? winSum / lossSum : wins > 0 ? Infinity : 0

    const dailyMap = new Map<string, { pnl: number; netPnl: number; count: number; wins: number; losses: number }>()
    for (const t of trades) {
      if (!t.exited_at) continue
      const day = String(t.exited_at).slice(0, 10)
      const entry = dailyMap.get(day) || { pnl: 0, netPnl: 0, count: 0, wins: 0, losses: 0 }
      entry.pnl += Number(t.pnl)
      entry.netPnl += Number(t.net_pnl)
      entry.count++
      if (Number(t.net_pnl) > 0) entry.wins++
      else entry.losses++
      dailyMap.set(day, entry)
    }

    const dailyPnl = [...dailyMap.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, stats]) => ({
        date,
        pnl: Math.round(stats.pnl * 100) / 100,
        netPnl: Math.round(stats.netPnl * 100) / 100,
        trades: stats.count,
        wins: stats.wins,
        losses: stats.losses,
      }))

    const maxPnl = Math.max(...dailyPnl.map(d => Math.abs(d.netPnl)), 1)

    return NextResponse.json({
      grossPnl: Math.round(grossPnl * 100) / 100,
      winRate: Math.round(winRate * 100) / 100,
      profitFactor: profitFactor === Infinity ? -1 : Math.round(profitFactor * 100) / 100,
      openPositions: openCount || 0,
      totalTrades,
      tradeStats: { wins, losses },
      dailyPnl,
      maxPnl,
    })
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
