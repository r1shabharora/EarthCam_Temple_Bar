import { NextResponse } from "next/server";
import pool from "@/lib/db";

export const revalidate = 0;

export async function GET() {
  try {
    const { rows } = await pool.query(`
      SELECT
        person_count,
        confidences,
        bounding_boxes,
        to_char(timestamp AT TIME ZONE 'UTC', 'HH24:MI:SS') AS time
      FROM detections
      ORDER BY timestamp DESC
      LIMIT 1
    `);
    if (!rows.length) return NextResponse.json(null);
    return NextResponse.json(rows[0]);
  } catch (err) {
    console.error(err);
    return NextResponse.json(null, { status: 500 });
  }
}
