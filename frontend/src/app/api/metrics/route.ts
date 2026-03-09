import { Pool } from "pg";
import { NextResponse } from "next/server";

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export const revalidate = 0;

export async function GET() {
  try {
    const { rows } = await pool.query(`
      SELECT
        -- Current occupancy: latest frame's person_count
        (SELECT person_count FROM detections ORDER BY timestamp DESC LIMIT 1)
          AS current_count,

        -- Today: unique persons who crossed the counting line (IN direction)
        COALESCE(SUM(count_in) FILTER (
          WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC')
        ), 0) AS total_today,

        -- Today: persons who crossed OUT
        COALESCE(SUM(count_out) FILTER (
          WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC')
        ), 0) AS total_today_out,

        -- This month: line crossings IN
        COALESCE(SUM(count_in) FILTER (
          WHERE timestamp >= date_trunc('month', now() AT TIME ZONE 'UTC')
        ), 0) AS total_month,

        -- All time: line crossings IN
        COALESCE(SUM(count_in), 0) AS total_all_time,

        -- Peak occupancy in a single frame today
        COALESCE(MAX(person_count) FILTER (
          WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC')
        ), 0) AS peak_today,

        -- Total frames logged today
        COUNT(*) FILTER (
          WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC')
        ) AS frames_today

      FROM detections
    `);

    return NextResponse.json(rows[0]);
  } catch (err) {
    console.error("Metrics query error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
