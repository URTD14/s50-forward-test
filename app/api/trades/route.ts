import { NextRequest, NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export async function GET(request: NextRequest) {
  try {
    const supabase = getSupabase()
    const tf = request.nextUrl.searchParams.get('tf')
    const limit = Math.min(parseInt(request.nextUrl.searchParams.get('limit') || '100', 10), 500)

    let query = supabase
      .from('trades')
      .select('*')
      .order('exited_at', { ascending: false })
      .limit(limit)

    if (tf && ['1m', '5m', '15m'].includes(tf)) {
      query = query.eq('timeframe', tf)
    }

    const { data: trades, error } = await query

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 })
    }

    return NextResponse.json({ trades, total: trades?.length || 0 })
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
