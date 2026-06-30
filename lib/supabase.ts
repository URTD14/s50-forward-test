import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY || ''

const key = serviceRoleKey || supabaseAnonKey

export function getSupabase() {
  if (!supabaseUrl || !key) {
    throw new Error('Missing Supabase environment variables')
  }
  return createClient(supabaseUrl, key)
}
