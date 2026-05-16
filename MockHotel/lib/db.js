import pg from "pg";

const { Pool } = pg;

const connectionString =
  process.env.DATABASE_URL || "postgres://postgres:postgres@localhost:55432/dev";

const globalForPg = globalThis;

export const pool =
  globalForPg.mockHotelPool ||
  new Pool({
    connectionString
  });

if (process.env.NODE_ENV !== "production") {
  globalForPg.mockHotelPool = pool;
}

export async function query(text, params = []) {
  return pool.query(text, params);
}
