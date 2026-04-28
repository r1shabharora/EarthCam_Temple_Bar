import { Pool } from "pg";

// Vercel serverless: each function instance is isolated.
// A module-level Pool is reused within the same warm instance but NOT across instances.
// max:1 ensures we never hold more than one connection per instance,
// preventing connection exhaustion on Supabase (which has a ~60 connection limit).
//
// For production at higher scale, swap DATABASE_URL for Supabase's
// Transaction Pooler URL (Settings → Database → Connection Pooling → port 6543).
declare global {
  // Persist the pool across hot-reloads in Next.js dev mode
  // eslint-disable-next-line no-var
  var _pgPool: Pool | undefined;
}

function createPool(): Pool {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL environment variable is not set.");
  }
  return new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 1,              // one connection per serverless instance
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 5_000,
  });
}

// Reuse pool across hot-reloads in dev; create fresh in production
const pool: Pool = globalThis._pgPool ?? createPool();
if (process.env.NODE_ENV !== "production") globalThis._pgPool = pool;

export default pool;
