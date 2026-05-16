CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TABLE IF EXISTS property_price CASCADE;
DROP TABLE IF EXISTS market_data_summary CASCADE;
DROP TABLE IF EXISTS pricing_record CASCADE;
DROP TABLE IF EXISTS revy_conversation CASCADE;
DROP TABLE IF EXISTS revy_state CASCADE;
DROP TABLE IF EXISTS hotel_home_dashboard CASCADE;
DROP TABLE IF EXISTS account_channel CASCADE;
DROP TABLE IF EXISTS external_account CASCADE;
DROP TABLE IF EXISTS property CASCADE;
DROP TABLE IF EXISTS account CASCADE;

CREATE TABLE account (
  id UUID UNIQUE PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'host',
  account_type TEXT NOT NULL CHECK (account_type IN ('airbnb', 'hotel')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE property (
  id TEXT PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  min_price_cents INTEGER NOT NULL CHECK (min_price_cents >= 0),
  max_price_cents INTEGER NOT NULL CHECK (max_price_cents >= min_price_cents),
  pricing_horizon INTEGER NOT NULL CHECK (pricing_horizon BETWEEN 1 AND 730),
  my_place TEXT,
  room_count INTEGER CHECK (room_count >= 0),
  capacity INTEGER CHECK (capacity >= 0),
  zip_code TEXT,
  county TEXT,
  state TEXT,
  city TEXT,
  bed TEXT,
  bath TEXT,
  other_info TEXT,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE property_price (
  property_id TEXT NOT NULL REFERENCES property(id) ON DELETE CASCADE,
  price_date DATE NOT NULL,
  fixed_price_cents INTEGER NOT NULL CHECK (fixed_price_cents >= 0),
  agent_price_cents INTEGER NOT NULL CHECK (agent_price_cents >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (property_id, price_date)
);

CREATE TABLE market_data_summary (
  id TEXT PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  property_id TEXT NOT NULL REFERENCES property(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  tool TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('completed', 'skipped', 'failed')),
  summary TEXT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_id, property_id, run_id, stage, tool, start_date, end_date)
);

CREATE TABLE pricing_record (
  id TEXT PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  record_type TEXT NOT NULL CHECK (record_type IN ('pending_task', 'price_log')),
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE external_account (
  id TEXT NOT NULL,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, id)
);

CREATE TABLE account_channel (
  id TEXT NOT NULL,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, id)
);

CREATE TABLE hotel_home_dashboard (
  id TEXT NOT NULL,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, id)
);

CREATE TABLE revy_state (
  account_id UUID PRIMARY KEY REFERENCES account(id) ON DELETE CASCADE,
  data JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE revy_conversation (
  id TEXT PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  property_id TEXT,
  title TEXT NOT NULL,
  final_message_at TIMESTAMPTZ NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX property_account_id_idx ON property(account_id);
CREATE INDEX property_price_date_idx ON property_price(price_date);
CREATE INDEX market_data_summary_account_property_date_idx ON market_data_summary(account_id, property_id, start_date, end_date);
CREATE INDEX market_data_summary_run_idx ON market_data_summary(run_id);
CREATE INDEX pricing_record_account_type_idx ON pricing_record(account_id, record_type);
CREATE INDEX external_account_account_idx ON external_account(account_id);
CREATE INDEX account_channel_account_idx ON account_channel(account_id);
CREATE INDEX hotel_home_dashboard_account_idx ON hotel_home_dashboard(account_id);
CREATE INDEX revy_conversation_account_time_idx ON revy_conversation(account_id, final_message_at DESC);
CREATE INDEX revy_conversation_account_property_idx ON revy_conversation(account_id, property_id, final_message_at DESC);
