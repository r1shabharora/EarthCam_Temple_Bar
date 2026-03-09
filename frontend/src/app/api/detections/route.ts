import { Pool } from "pg";
import { NextResponse } from "next/server";

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export const revalidate = 0;

export async function GET() {
  try {
    // Last 60 detections for the chart (1 per second ≈ last 60s)
    const chart = await pool.query(`
      SELECT
        to_char(timestamp AT TIME ZONE 'UTC', 'HH24:MI:SS') AS time,
        person_count
      FROM detections
      ORDER BY timestamp DESC
      LIMIT 60
    `);

    // Last 10 rows for the table
    const recent = await pool.query(`
      SELECT
        to_char(timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS timestamp,
        frame_number,
        person_count,
        confidences,
        bounding_boxes
      FROM detections
      ORDER BY timestamp DESC
      LIMIT 10
    `);

    return NextResponse.json({
      chart: chart.rows.reverse(),   // oldest → newest for chart
      recent: recent.rows,
    });
  } catch (err) {
    console.error("Detections query error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
