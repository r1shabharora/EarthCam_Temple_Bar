import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EarthCam — AI Person Detection",
  description: "Real-time person detection dashboard powered by YOLOv8",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased min-h-screen">
        <div className="scan-line" />
        {/* Dot grid background */}
        <div
          className="fixed inset-0 pointer-events-none"
          style={{
            backgroundImage: "radial-gradient(circle, rgba(0,255,136,0.06) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        {/* Radial vignette */}
        <div
          className="fixed inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse at center, transparent 40%, rgba(5,5,8,0.8) 100%)",
          }}
        />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
