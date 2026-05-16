DROP TABLE IF EXISTS room_type_price CASCADE;
DROP TABLE IF EXISTS room_type CASCADE;
DROP TABLE IF EXISTS room_price CASCADE;
DROP TABLE IF EXISTS room CASCADE;
DROP TABLE IF EXISTS account CASCADE;

CREATE TABLE account (
  id UUID UNIQUE PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'manager',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE room_type (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  room_type TEXT NOT NULL,
  room_count INTEGER NOT NULL CHECK (room_count >= 0),
  capacity INTEGER CHECK (capacity >= 0),
  bed TEXT,
  bath TEXT,
  min_price_cents INTEGER NOT NULL CHECK (min_price_cents >= 0),
  max_price_cents INTEGER NOT NULL CHECK (max_price_cents >= min_price_cents),
  base_price_cents INTEGER NOT NULL CHECK (base_price_cents >= 0),
  pricing_horizon INTEGER NOT NULL CHECK (pricing_horizon BETWEEN 1 AND 730),
  source TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE room_type_price (
  room_type_id TEXT NOT NULL REFERENCES room_type(id) ON DELETE CASCADE,
  stay_date DATE NOT NULL,
  price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
  updated_by UUID REFERENCES account(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (room_type_id, stay_date)
);

CREATE INDEX room_type_price_stay_date_idx ON room_type_price(stay_date);
