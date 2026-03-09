"use client";
import { useEffect, useState, useCallback } from "react";
import { Users, UserCheck, Calendar, BarChart3, Zap, Activity } from "lucide-react";
import MetricCard from "@/components/MetricCard";
import LiveFeed from "@/components/LiveFeed";
import DetectionChart from "@/components/DetectionChart";
import RecentTable from "@/components/RecentTable";

interface Metrics {
  current_count: number;
  total_today: number;
  total_today_out: number;
  total_month: number;
  total_all_time: number;
  peak_today: number;
  frames_today: number;
}

interface DetectionData {
  chart: { time: string; person_count: number }[];
  recent: any[];
}

const POLL_INTERVAL = 5000; // 5 seconds

export default function Dashboard() {
  const [metrics, setMetrics]     = useState<Metrics | null>(null);
  const [detections, setDetections] = useState<DetectionData>({ chart: [], recent: [] });
  const [loading, setLoading]     = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [error, setError]         = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [mRes, dRes] = await Promise.all([
        fetch("/api/metrics", { cache: "no-store" }),
        fetch("/api/detections", { cache: "no-store" }),
      ]);
      if (!mRes.ok || !dRes.ok) throw new Error("API error");
      const [m, d] = await Promise.all([mRes.json(), dRes.json()]);
      setMetrics(m);
      setDetections(d);
      setLastUpdated(new Date().toLocaleTimeString());
      setError(null);
    } catch (e) {
      setError("Failed to fetch data — retrying…");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <div className="min-h-screen px-4 py-6 md:px-8 md:py-8 max-w-[1600px] mx-auto">

      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-6 h-6 rounded bg-[rgba(0,255,136,0.1)] border border-[rgba(0,255,136,0.3)] flex items-center justify-center">
              <Zap size={12} className="text-[#00ff88]" />
            </div>
            <span className="text-[10px] font-bold tracking-[0.2em] text-[#00ff88] uppercase">EarthCam AI</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-white tracking-tight">
            Person Detection{" "}
            <span className="text-[#00ff88]">Dashboard</span>
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Real-time surveillance analytics · YOLOv8 · Temple Bar Live
          </p>
        </div>

        <div className="flex items-center gap-3">
          {error && (
            <span className="text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-full px-3 py-1">
              {error}
            </span>
          )}
          <div className="glass rounded-full px-4 py-2 flex items-center gap-2">
            <Activity size={12} className="text-[#00ff88]" />
            <span className="text-xs text-slate-400 font-mono">
              {lastUpdated ? `Updated ${lastUpdated}` : "Connecting…"}
            </span>
          </div>
        </div>
      </header>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 mb-6">
        <MetricCard
          label="Current Count"
          value={metrics?.current_count ?? 0}
          icon={Users}
          accent="green"
          loading={loading}
        />
        <MetricCard
          label="Entered Today"
          value={metrics?.total_today ?? 0}
          icon={UserCheck}
          accent="green"
          loading={loading}
        />
        <MetricCard
          label="Exited Today"
          value={metrics?.total_today_out ?? 0}
          icon={Activity}
          accent="green"
          loading={loading}
        />
        <MetricCard
          label="Entered This Month"
          value={metrics?.total_month ?? 0}
          icon={Calendar}
          accent="cyan"
          loading={loading}
        />
        <MetricCard
          label="Entered All Time"
          value={metrics?.total_all_time ?? 0}
          icon={BarChart3}
          accent="cyan"
          loading={loading}
        />
        <MetricCard
          label="Peak Occupancy"
          value={metrics?.peak_today ?? 0}
          icon={Zap}
          accent="white"
          loading={loading}
        />
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4">
        {/* Live feed — takes 2/3 width */}
        <div className="xl:col-span-2">
          <LiveFeed
            currentCount={metrics?.current_count ?? 0}
            loading={loading}
          />
        </div>

        {/* Detection chart — takes 1/3 */}
        <div className="xl:col-span-1">
          <DetectionChart data={detections.chart} loading={loading} />
        </div>
      </div>

      {/* Recent detections table */}
      <RecentTable rows={detections.recent} loading={loading} />

      {/* Footer */}
      <footer className="mt-8 flex items-center justify-between text-[10px] text-slate-700 font-mono">
        <span>EARTHCAM AI · TEMPLE BAR · DUBLIN</span>
        <span>REFRESH INTERVAL: {POLL_INTERVAL / 1000}s</span>
      </footer>
    </div>
  );
}
