"use client";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";

interface DataPoint { time: string; person_count: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#050508]/95 border border-[rgba(0,255,136,0.2)] rounded-lg px-3 py-2 text-xs">
      <p className="text-slate-400 mb-1">{label}</p>
      <p className="text-[#00ff88] font-bold">{payload[0].value} persons</p>
    </div>
  );
};

export default function DetectionChart({ data, loading }: { data: DataPoint[]; loading: boolean }) {
  return (
    <div className="glass rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">Detection Timeline</h2>
          <p className="text-xs text-slate-500 mt-0.5">Persons per second — last 60 samples</p>
        </div>
        <span className="text-[10px] text-slate-600 font-mono uppercase tracking-widest">Live · 1s interval</span>
      </div>

      {loading || data.length === 0 ? (
        <div className="h-48 flex items-center justify-center">
          <div className="text-slate-600 text-xs font-mono animate-pulse">Awaiting data…</div>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="personGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis
              dataKey="time"
              tick={{ fill: "#475569", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: "#475569", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="person_count"
              stroke="#00ff88"
              strokeWidth={2}
              fill="url(#personGrad)"
              dot={false}
              activeDot={{ r: 4, fill: "#00ff88", strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
