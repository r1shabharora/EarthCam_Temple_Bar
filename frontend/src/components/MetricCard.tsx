"use client";
import { LucideIcon } from "lucide-react";
import clsx from "clsx";

interface Props {
  label: string;
  value: number | string;
  icon: LucideIcon;
  accent?: "green" | "cyan" | "white";
  suffix?: string;
  loading?: boolean;
}

const accentMap = {
  green: { text: "text-[#00ff88]", shadow: "shadow-[0_0_20px_rgba(0,255,136,0.15)]", icon: "text-[#00ff88]" },
  cyan:  { text: "text-[#00d4ff]", shadow: "shadow-[0_0_20px_rgba(0,212,255,0.15)]", icon: "text-[#00d4ff]" },
  white: { text: "text-white",     shadow: "",                                          icon: "text-slate-400" },
};

export default function MetricCard({ label, value, icon: Icon, accent = "green", suffix, loading }: Props) {
  const a = accentMap[accent];
  return (
    <div className={clsx("glass rounded-2xl p-6 flex flex-col gap-3 animate-slide-up", a.shadow)}>
      <div className="flex items-center justify-between">
        <span className="text-slate-400 text-xs font-semibold uppercase tracking-widest">{label}</span>
        <div className={clsx("p-2 rounded-lg bg-white/5", a.icon)}>
          <Icon size={16} />
        </div>
      </div>
      <div className="flex items-end gap-1">
        {loading ? (
          <div className="h-10 w-24 bg-white/5 rounded-lg animate-pulse" />
        ) : (
          <>
            <span className={clsx("text-4xl font-bold metric-value", a.text)}>{value.toLocaleString()}</span>
            {suffix && <span className="text-slate-500 text-sm mb-1.5">{suffix}</span>}
          </>
        )}
      </div>
    </div>
  );
}
