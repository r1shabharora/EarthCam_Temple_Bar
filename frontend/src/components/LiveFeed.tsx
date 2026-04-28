"use client";
import { useEffect, useRef, useState } from "react";

// Production: set NEXT_PUBLIC_STREAM_URL in the Vercel dashboard to your backend's public URL.
// Fallback to localhost for local dev only — the browser must be able to reach this address.
const STREAM_URL = process.env.NEXT_PUBLIC_STREAM_URL ?? "http://localhost:8080/stream";

interface Props {
  currentCount: number;
  loading: boolean;
}

export default function LiveFeed({ currentCount, loading }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "error">("connecting");

  const connect = () => {
    if (!imgRef.current) return;
    // Cache-bust to force a fresh connection on retry
    imgRef.current.src = `${STREAM_URL}?t=${Date.now()}`;
    setStatus("connecting");
  };

  useEffect(() => {
    connect();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusColor = { connecting: "#f59e0b", live: "#00ff88", error: "#ef4444" }[status];
  const statusLabel = { connecting: "Connecting…", live: "Live", error: "Reconnecting…" }[status];

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[rgba(0,255,136,0.1)] shrink-0">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{
              background: statusColor,
              boxShadow: `0 0 6px ${statusColor}`,
              animation: status === "live" ? "live-pulse 2s ease-in-out infinite" : "none",
            }}
          />
          <span className="text-xs font-bold tracking-widest uppercase" style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 bg-black/40 rounded-full px-3 py-1">
            <svg width="8" height="8" viewBox="0 0 8 8">
              <circle cx="4" cy="4" r="4" fill="#00ff88" opacity="0.9" />
            </svg>
            <span className="text-xs text-[#00ff88] font-mono font-semibold">
              {loading ? "—" : currentCount} persons
            </span>
          </div>
          <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">YOLOv8 · MJPEG</span>
        </div>
      </div>

      {/* Stream container */}
      <div className="relative flex-1 bg-black" style={{ minHeight: "360px" }}>

        {/* MJPEG — browser handles the multipart stream natively via <img> */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={imgRef}
          alt="Live YOLO detection feed"
          className="absolute inset-0 w-full h-full object-contain"
          style={{ display: status === "error" ? "none" : "block" }}
          onLoad={() => setStatus("live")}
          onError={() => {
            setStatus("error");
            setTimeout(connect, 3000);
          }}
        />

        {/* Connecting / error overlay */}
        {status !== "live" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 border-2 border-[#00ff88]/20 border-t-[#00ff88] rounded-full animate-spin" />
            <span className="text-xs text-slate-500 font-mono">
              {status === "error"
                ? "Stream offline — retrying in 3 s…"
                : `Connecting to ${STREAM_URL}…`}
            </span>
            <span className="text-[10px] text-slate-700 font-mono">
              Run: python detection.py --url &lt;youtube-url&gt;
            </span>
          </div>
        )}

        {/* Corner brackets (only when live) */}
        {status === "live" && (
          <>
            <div className="absolute top-2 left-2 w-5 h-5 border-t-2 border-l-2 border-[#00ff88] opacity-40 pointer-events-none" />
            <div className="absolute top-2 right-2 w-5 h-5 border-t-2 border-r-2 border-[#00ff88] opacity-40 pointer-events-none" />
            <div className="absolute bottom-2 left-2 w-5 h-5 border-b-2 border-l-2 border-[#00ff88] opacity-40 pointer-events-none" />
            <div className="absolute bottom-2 right-2 w-5 h-5 border-b-2 border-r-2 border-[#00ff88] opacity-40 pointer-events-none" />
          </>
        )}
      </div>
    </div>
  );
}
