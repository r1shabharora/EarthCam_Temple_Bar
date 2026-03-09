"use client";

interface Row {
  timestamp: string;
  frame_number: number;
  person_count: number;
  confidences: number[];
  bounding_boxes: { x1: number; y1: number; x2: number; y2: number }[];
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "#00ff88" : pct >= 50 ? "#00d4ff" : "#f59e0b";
  return (
    <span
      className="inline-block text-[10px] font-mono px-1.5 py-0.5 rounded"
      style={{ color, background: `${color}15`, border: `1px solid ${color}30` }}
    >
      {pct}%
    </span>
  );
}

export default function RecentTable({ rows, loading }: { rows: Row[]; loading: boolean }) {
  return (
    <div className="glass rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Recent Detections</h2>
        <span className="text-[10px] text-slate-600 font-mono uppercase tracking-widest">Latest 10</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/5">
              {["Timestamp (UTC)", "Frame", "Count", "Confidences"].map((h) => (
                <th key={h} className="text-left text-slate-500 font-semibold pb-2 pr-4 uppercase tracking-wider text-[10px]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading || rows.length === 0 ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-white/[0.03]">
                  {Array.from({ length: 4 }).map((_, j) => (
                    <td key={j} className="py-2.5 pr-4">
                      <div className="h-3 bg-white/5 rounded animate-pulse" style={{ width: `${[120,40,30,80][j]}px` }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              rows.map((row, i) => (
                <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                  <td className="py-2.5 pr-4 font-mono text-slate-400">{row.timestamp}</td>
                  <td className="py-2.5 pr-4 font-mono text-slate-500">#{row.frame_number.toLocaleString()}</td>
                  <td className="py-2.5 pr-4">
                    <span className="text-[#00ff88] font-bold font-mono">{row.person_count}</span>
                  </td>
                  <td className="py-2.5 pr-4 flex flex-wrap gap-1">
                    {(row.confidences ?? []).slice(0, 5).map((c, j) => (
                      <ConfidenceBadge key={j} value={c} />
                    ))}
                    {(row.confidences ?? []).length > 5 && (
                      <span className="text-slate-600 text-[10px] self-center">+{row.confidences.length - 5}</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
