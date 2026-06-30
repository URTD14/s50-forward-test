-- Run this in your Supabase SQL Editor (https://supabase.com/dashboard/project/roxiyshdxpymmcnsiqpz/sql/new)

CREATE TABLE IF NOT EXISTS config (
  id serial PRIMARY KEY,
  param text UNIQUE NOT NULL,
  value numeric NOT NULL
);
INSERT INTO config (param, value) VALUES
  ('capital', 15000), ('rr', 1.0), ('risk_pct', 0.75),
  ('vol_mult', 1.5), ('max_trades_per_day', 10)
ON CONFLICT (param) DO NOTHING;

CREATE TABLE IF NOT EXISTS signals (
  id serial PRIMARY KEY,
  detected_at timestamptz NOT NULL DEFAULT now(),
  trade_date date NOT NULL,
  timeframe text NOT NULL,
  bar_time timestamptz NOT NULL,
  direction text NOT NULL CHECK (direction IN ('BUY','SELL')),
  entry_price numeric NOT NULL,
  sl_price numeric NOT NULL,
  tp_price numeric NOT NULL,
  pdh numeric, pdl numeric, pdr numeric,
  vwap numeric, volume bigint, vol_avg numeric,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','closed')),
  exit_price numeric, pnl numeric, costs numeric, net_pnl numeric,
  exit_reason text, closed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(timeframe, bar_time, direction)
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_trade_date ON signals(trade_date);
CREATE INDEX IF NOT EXISTS idx_signals_timeframe_bar ON signals(timeframe, bar_time);

CREATE TABLE IF NOT EXISTS open_positions (
  id serial PRIMARY KEY,
  signal_id integer UNIQUE REFERENCES signals(id),
  timeframe text NOT NULL,
  trade_date date NOT NULL,
  direction text NOT NULL,
  entry_price numeric NOT NULL,
  sl_price numeric NOT NULL,
  tp_price numeric NOT NULL,
  quantity integer NOT NULL,
  entered_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_open_positions_tf ON open_positions(timeframe);

CREATE TABLE IF NOT EXISTS trades (
  id serial PRIMARY KEY,
  signal_id integer REFERENCES signals(id),
  timeframe text NOT NULL,
  trade_date date NOT NULL,
  direction text NOT NULL,
  entry_price numeric NOT NULL,
  exit_price numeric NOT NULL,
  sl_price numeric NOT NULL,
  tp_price numeric NOT NULL,
  quantity integer NOT NULL,
  pnl numeric NOT NULL,
  brokerage numeric, stt numeric,
  exchange_charges numeric, sebi_charges numeric,
  gst numeric, stamp_duty numeric,
  total_costs numeric, net_pnl numeric,
  exit_reason text NOT NULL CHECK (exit_reason IN ('tp_hit','sl_hit','cutoff')),
  entered_at timestamptz NOT NULL,
  exited_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date);

CREATE TABLE IF NOT EXISTS daily_summary (
  id serial PRIMARY KEY,
  date date NOT NULL,
  timeframe text NOT NULL,
  total_signals int DEFAULT 0, total_trades int DEFAULT 0,
  wins int DEFAULT 0, losses int DEFAULT 0,
  gross_pnl numeric DEFAULT 0, net_pnl numeric DEFAULT 0,
  created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
  UNIQUE(date, timeframe)
);
