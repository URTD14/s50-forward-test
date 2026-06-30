'use client'

import { useState, useEffect, useCallback } from 'react'

interface DashboardData {
  grossPnl: number
  winRate: number
  profitFactor: number
  openPositions: number
  totalTrades: number
  tradeStats: { wins: number; losses: number }
  dailyPnl: Array<{ date: string; netPnl: number; trades: number; wins: number; losses: number }>
  maxPnl: number
}

interface Signal {
  id: number
  timeframe: string
  direction: string
  bar_time: string
  entry_price: number
  sl_price: number
  tp_price: number
  pdh?: number
  pdl?: number
  vwap?: number
  volume?: number
  vol_avg?: number
  status: string
  pnl: number | null
  net_pnl: number | null
}

interface Trade {
  id: number
  timeframe: string
  direction: string
  entry_price: number
  exit_price: number
  pnl: number
  net_pnl: number
  brokerage?: number
  exit_reason: string
  entered_at: string
  exited_at: string
  quantity: number
}

const TF_COLORS: Record<string, string> = {
  '1m': '#3b82f6',
  '5m': '#a855f7',
  '15m': '#22c55e',
}

function formatTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
}

function formatPnL(val: number | null | undefined) {
  if (val == null) return '—'
  const prefix = val >= 0 ? '+' : ''
  return `${prefix}${val.toFixed(2)}`
}

function TabBar({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #1f1f1f', marginBottom: 24 }}>
      {tabs.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          style={{
            padding: '12px 24px',
            background: 'transparent',
            border: 'none',
            color: active === t ? '#22c55e' : '#666',
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
            borderBottom: active === t ? '2px solid #22c55e' : '2px solid transparent',
            transition: 'all 0.15s',
          }}
        >
          {t}
        </button>
      ))}
    </div>
  )
}

function SummaryCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      background: '#111',
      borderRadius: 10,
      padding: '16px 20px',
      border: '1px solid #1f1f1f',
      flex: 1,
      minWidth: 150,
    }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || '#e5e5e5' }}>{value}</div>
    </div>
  )
}

function DailyChart({ dailyPnl, maxPnl }: { dailyPnl: DashboardData['dailyPnl']; maxPnl: number }) {
  const barCount = dailyPnl.length
  if (barCount === 0) {
    return <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>No daily data yet</div>
  }

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 180, padding: '20px 0' }}>
      {dailyPnl.map((d, i) => {
        const pct = Math.abs(d.netPnl) / maxPnl
        const height = Math.max(4, pct * 150)
        const isGreen = d.netPnl >= 0
        return (
          <div key={d.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div
              title={`${d.date}: ${formatPnL(d.netPnl)} (${d.trades} trades)`}
              style={{
                width: '80%',
                height,
                background: isGreen ? '#22c55e' : '#ef4444',
                borderRadius: '3px 3px 0 0',
                opacity: 0.85,
                transition: 'height 0.3s',
                minHeight: 4,
              }}
            />
            {barCount <= 10 && (
              <span style={{ fontSize: 10, color: '#666' }}>{d.date.slice(5)}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function Page() {
  const [activeTab, setActiveTab] = useState('Dashboard')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [signals, setSignals] = useState<Signal[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [tfFilter, setTfFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard')
      const data = await res.json()
      if (!data.error) setDashboard(data)
    } catch { /* ignore */ }
  }, [])

  const fetchSignals = useCallback(async (tf?: string) => {
    try {
      const url = tf && tf !== 'all' ? `/api/signals?tf=${tf}` : '/api/signals'
      const res = await fetch(url)
      const data = await res.json()
      if (data.signals) setSignals(data.signals)
    } catch { /* ignore */ }
  }, [])

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch('/api/trades')
      const data = await res.json()
      if (data.trades) setTrades(data.trades)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    Promise.all([fetchDashboard(), fetchSignals(), fetchTrades()]).finally(() => setLoading(false))
  }, [fetchDashboard, fetchSignals, fetchTrades])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => {
      fetchDashboard()
      fetchSignals(tfFilter === 'all' ? undefined : tfFilter)
      fetchTrades()
    }, 30000)
    return () => clearInterval(interval)
  }, [autoRefresh, fetchDashboard, fetchSignals, fetchTrades, tfFilter])

  const handleTfChange = (val: string) => {
    setTfFilter(val)
    fetchSignals(val === 'all' ? undefined : val)
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div style={{ color: '#666', fontSize: 16 }}>Loading...</div>
      </div>
    )
  }

  const tabs = ['Dashboard', 'Signals Log', 'Trade Log']

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.01em' }}>S50 Forward Test</h1>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#888', fontSize: 13, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
            style={{ accentColor: '#22c55e' }}
          />
          Auto-refresh (30s)
        </label>
      </div>

      <TabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />

      {activeTab === 'Dashboard' && (
        <div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
            <SummaryCard label="Net P&L" value={`₹${formatPnL(dashboard?.grossPnl ?? 0)}`} color={((dashboard?.grossPnl ?? 0) >= 0) ? '#22c55e' : '#ef4444'} />
            <SummaryCard label="Win Rate" value={`${dashboard?.winRate ?? 0}%`} />
            <SummaryCard
              label="Profit Factor"
              value={dashboard?.profitFactor === -1 ? '∞' : String(dashboard?.profitFactor ?? 0)}
            />
            <SummaryCard label="Open Positions" value={String(dashboard?.openPositions ?? 0)} />
            <SummaryCard label="Total Trades" value={String(dashboard?.totalTrades ?? 0)} />
          </div>

          <div style={{ background: '#111', borderRadius: 10, border: '1px solid #1f1f1f', padding: '16px 20px', marginBottom: 24 }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: '#888', marginBottom: 8 }}>Daily P&L</h2>
            <DailyChart dailyPnl={dashboard?.dailyPnl ?? []} maxPnl={dashboard?.maxPnl ?? 1} />
          </div>

          <div style={{ background: '#111', borderRadius: 10, border: '1px solid #1f1f1f', padding: '16px 20px' }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: '#888', marginBottom: 12 }}>Latest Signals</h2>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>TF</th>
                  <th>Direction</th>
                  <th>Entry</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {signals.slice(0, 10).map(s => (
                  <tr key={s.id}>
                    <td style={{ color: '#999', fontSize: 13 }}>{formatTime(s.bar_time)}</td>
                    <td>
                      <span style={{ color: TF_COLORS[s.timeframe] || '#888', fontSize: 12 }}>{s.timeframe}</span>
                    </td>
                    <td style={{ color: s.direction === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {s.direction}
                    </td>
                    <td>{s.entry_price}</td>
                    <td style={{ color: '#ef4444' }}>{s.sl_price}</td>
                    <td style={{ color: '#22c55e' }}>{s.tp_price}</td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        background:
                          s.status === 'closed' ? '#1a2a1a' :
                          s.status === 'active' ? '#1a1a2a' :
                          '#1f1f1f',
                        color:
                          s.status === 'closed' ? '#22c55e' :
                          s.status === 'active' ? '#3b82f6' :
                          '#888',
                      }}>
                        {s.status}
                      </span>
                    </td>
                  </tr>
                ))}
                {signals.length === 0 && (
                  <tr><td colSpan={7} style={{ textAlign: 'center', color: '#666', padding: 24 }}>No signals yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'Signals Log' && (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
            <label style={{ color: '#888', fontSize: 13 }}>Timeframe:</label>
            <select value={tfFilter} onChange={e => handleTfChange(e.target.value)}>
              <option value="all">All</option>
              <option value="1m">1m</option>
              <option value="5m">5m</option>
              <option value="15m">15m</option>
            </select>
            <span style={{ color: '#555', fontSize: 12 }}>{signals.length} signals</span>
          </div>
          <div style={{ background: '#111', borderRadius: 10, border: '1px solid #1f1f1f', padding: '16px 20px', overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>TF</th>
                  <th>Direction</th>
                  <th>Entry</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>PDH</th>
                  <th>PDL</th>
                  <th>VWAP</th>
                  <th>Volume</th>
                  <th>Vol Avg</th>
                  <th>Status</th>
                  <th>P&L</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(s => (
                  <tr key={s.id}>
                    <td style={{ color: '#999', fontSize: 13, whiteSpace: 'nowrap' }}>{formatTime(s.bar_time)}</td>
                    <td>
                      <span style={{ color: TF_COLORS[s.timeframe] || '#888', fontSize: 12 }}>{s.timeframe}</span>
                    </td>
                    <td style={{ color: s.direction === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {s.direction}
                    </td>
                    <td>{s.entry_price}</td>
                    <td style={{ color: '#ef4444' }}>{s.sl_price}</td>
                    <td style={{ color: '#22c55e' }}>{s.tp_price}</td>
                    <td>{s.pdh ?? '—'}</td>
                    <td>{s.pdl ?? '—'}</td>
                    <td>{s.vwap != null ? Number(s.vwap).toFixed(2) : '—'}</td>
                    <td>{s.volume != null ? Number(s.volume).toFixed(0) : '—'}</td>
                    <td>{s.vol_avg != null ? Number(s.vol_avg).toFixed(0) : '—'}</td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        background: s.status === 'closed' ? '#1a2a1a' : s.status === 'active' ? '#1a1a2a' : '#1f1f1f',
                        color: s.status === 'closed' ? '#22c55e' : s.status === 'active' ? '#3b82f6' : '#888',
                      }}>
                        {s.status}
                      </span>
                    </td>
                    <td style={{ color: (s.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {formatPnL(s.net_pnl)}
                    </td>
                  </tr>
                ))}
                {signals.length === 0 && (
                  <tr><td colSpan={13} style={{ textAlign: 'center', color: '#666', padding: 24 }}>No signals found</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'Trade Log' && (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
            <span style={{ color: '#555', fontSize: 12 }}>{trades.length} trades</span>
          </div>
          <div style={{ background: '#111', borderRadius: 10, border: '1px solid #1f1f1f', padding: '16px 20px', overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Entered</th>
                  <th>Exited</th>
                  <th>TF</th>
                  <th>Direction</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Qty</th>
                  <th>P&L</th>
                  <th>Brokerage</th>
                  <th>Net P&L</th>
                  <th>Exit Reason</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id}>
                    <td style={{ color: '#999', fontSize: 13, whiteSpace: 'nowrap' }}>{formatTime(t.entered_at)}</td>
                    <td style={{ color: '#999', fontSize: 13, whiteSpace: 'nowrap' }}>{formatTime(t.exited_at)}</td>
                    <td>
                      <span style={{ color: TF_COLORS[t.timeframe] || '#888', fontSize: 12 }}>{t.timeframe}</span>
                    </td>
                    <td style={{ color: t.direction === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {t.direction}
                    </td>
                    <td>{t.entry_price}</td>
                    <td>{t.exit_price}</td>
                    <td>{t.quantity}</td>
                    <td style={{ color: t.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {formatPnL(t.pnl)}
                    </td>
                    <td style={{ color: '#888' }}>{Number(t.brokerage || 0).toFixed(2)}</td>
                    <td style={{ color: t.net_pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                      {formatPnL(t.net_pnl)}
                    </td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        background: t.exit_reason === 'tp_hit' ? '#1a2a1a' : t.exit_reason === 'sl_hit' ? '#2a1a1a' : '#1a1a1a',
                        color: t.exit_reason === 'tp_hit' ? '#22c55e' : t.exit_reason === 'sl_hit' ? '#ef4444' : '#888',
                      }}>
                        {t.exit_reason}
                      </span>
                    </td>
                  </tr>
                ))}
                {trades.length === 0 && (
                  <tr><td colSpan={11} style={{ textAlign: 'center', color: '#666', padding: 24 }}>No trades yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
