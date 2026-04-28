# Implementation Guide — EarthCam Temple Bar

Full technical walkthrough: how every component is built, why each decision was made, and how to extend or replicate the system.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Detection Backend](#2-detection-backend)
3. [Tracking & Counting Logic](#3-tracking--counting-logic)
4. [MJPEG Streaming Server](#4-mjpeg-streaming-server)
5. [Database Layer](#5-database-layer)
6. [Frontend Dashboard](#6-frontend-dashboard)
7. [API Routes](#7-api-routes)
8. [Configuration Reference](#8-configuration-reference)
9. [Docker & CI/CD](#9-docker--cicd)
10. [Extending the System](#10-extending-the-system)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. System Architecture

### Component Map

```
┌─────────────────────────────────────────────────────────┐
│                    DETECTION BACKEND                     │
│                    (detection.py)                        │
│                                                         │
│  YouTube URL                                            │
│      │                                                  │
│      ▼                                                  │
│  yt-dlp ──► HLS manifest URL                           │
│      │                                                  │
│      ▼                                                  │
│  FFmpeg subprocess                                      │
│  (pipe: raw BGR24 frames, WxH bytes per frame)         │
│      │                                                  │
│      ▼                                                  │
│  numpy array reshape (H, W, 3)                         │
│      │                                                  │
│      ▼                                                  │
│  YOLOv8n.predict()                                     │
│  (class=0 only, conf≥CONF_THRESHOLD)                   │
│      │                                                  │
│      ▼                                                  │
│  ByteTrack.update()                                    │
│  (returns tracked boxes with persistent IDs)           │
│      │                                                  │
│      ├──────────────────────────────────────────────┐  │
│      ▼                                              │  │
│  Virtual Line Crossing Logic                        │  │
│  (IN/OUT per track, MIN_TRACK_AGE gate)             │  │
│      │                                              │  │
│      ▼                                              ▼  │
│  PostgreSQL INSERT              draw_frame() + JPEG │  │
│  (1 row/second)                 encode → MJPEG queue│  │
└─────────────────────────────────────────────────────┼──┘
                                                      │
                                    ┌─────────────────┘
                                    ▼
                          Flask /stream endpoint
                          (multipart/x-mixed-replace)
                                    │
                          ┌─────────▼──────────┐
                          │   BROWSER <img>     │
                          │   LiveFeed.tsx       │
                          └─────────────────────┘

┌──────────────────────────────────────────┐
│           SUPABASE POSTGRESQL             │
│           (detections table)              │
│                                          │
│  ◄── Python psycopg2 INSERT (backend)    │
│  ◄── Node pg SELECT (frontend API)       │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│         FRONTEND (Next.js 14)             │
│                                          │
│  page.tsx                                │
│  ├── MetricCard  ◄── /api/metrics        │
│  ├── LiveFeed    ◄── NEXT_PUBLIC_STREAM  │
│  ├── DetectionChart ◄── /api/detections  │
│  └── RecentTable ◄── /api/detections     │
└──────────────────────────────────────────┘
```

### Threading Model

`detection.py` runs three threads:

| Thread | Role |
|--------|------|
| Main thread | Frame reading loop, YOLOv8 inference, ByteTrack, DB writes |
| Flask thread (daemon) | Serves MJPEG HTTP stream from queue |
| (FFmpeg subprocess) | Separate OS process, piped stdout |

The MJPEG queue (`maxsize=1`) means the Flask thread always serves the most recent frame, dropping older frames if the consumer is slow.

---

## 2. Detection Backend

### Stream Acquisition

```python
# Step 1: resolve the live HLS URL
import yt_dlp

def get_stream_info(youtube_url: str) -> str:
    ydl_opts = {"format": "best[ext=mp4]/best", "quiet": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
    return info["url"]  # Direct HLS URL

# Step 2: pipe frames through FFmpeg
import subprocess

def open_ffmpeg_pipe(stream_url: str, width: int, height: int):
    cmd = [
        "ffmpeg", "-i", stream_url,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-vf", f"scale={width}:{height}",
        "-",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

# Step 3: read one frame
def read_frame(proc, width: int, height: int):
    raw = proc.stdout.read(width * height * 3)
    if len(raw) != width * height * 3:
        return None  # EOF or broken pipe
    return np.frombuffer(raw, np.uint8).reshape((height, width, 3))
```

FFmpeg outputs raw BGR24 bytes. Each frame is exactly `W × H × 3` bytes, so a short read signals stream end.

### YOLOv8 Inference

```python
from ultralytics import YOLO

model = YOLO("yolov8n.pt")

results = model.predict(
    frame,
    classes=[0],          # person only
    conf=CONF_THRESHOLD,  # 0.40 default
    verbose=False,
)

# Extract boxes and confidences
boxes = results[0].boxes.xyxy.cpu().numpy()       # [[x1,y1,x2,y2], ...]
confidences = results[0].boxes.conf.cpu().numpy() # [0.82, 0.61, ...]
```

Setting `classes=[0]` avoids running NMS across 80 classes — faster and no false positives from non-person classes.

---

## 3. Tracking & Counting Logic

### ByteTrack Integration

ByteTrack is built into Ultralytics. Pass detections directly:

```python
results = model.track(
    frame,
    classes=[0],
    conf=CONF_THRESHOLD,
    tracker="bytetrack_custom.yaml",
    persist=True,   # maintain track state across calls
    verbose=False,
)

tracked = results[0].boxes
track_ids = tracked.id.int().cpu().tolist()  # [1, 2, 5, 8, ...]
boxes     = tracked.xyxy.cpu().numpy()
```

`persist=True` is critical — without it, ByteTrack resets its internal state every frame, breaking track continuity.

### Virtual Line Crossing

```python
COUNT_LINE_POS  = 0.5   # centre of frame
COUNT_LINE_AXIS = "x"   # vertical line

def _foot_point(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, y2)  # bottom-centre

def _line_side(foot, frame_w, frame_h):
    fx, fy = foot
    if COUNT_LINE_AXIS == "x":
        return 1 if fx > COUNT_LINE_POS * frame_w else -1
    else:
        return 1 if fy > COUNT_LINE_POS * frame_h else -1

# Per-frame update
prev_sides = {}   # {track_id: last_side}
track_ages = {}   # {track_id: frame_count}
count_in   = 0
count_out  = 0

for track_id, box in zip(track_ids, boxes):
    track_ages[track_id] = track_ages.get(track_id, 0) + 1
    foot = _foot_point(box)
    side = _line_side(foot, W, H)

    if track_id in prev_sides and track_ages[track_id] >= MIN_TRACK_AGE:
        if prev_sides[track_id] == -1 and side == 1:
            count_in += 1
        elif prev_sides[track_id] == 1 and side == -1:
            count_out += 1

    prev_sides[track_id] = side
```

Stale tracks (lost by ByteTrack) are pruned from `prev_sides` each frame to prevent ghost crossings if a track ID is reused.

---

## 4. MJPEG Streaming Server

### Flask Setup

```python
from flask import Flask, Response
import queue, threading

app = Flask(__name__)
frame_queue = queue.Queue(maxsize=1)

def _push_jpeg(frame):
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    try:
        frame_queue.put_nowait(jpeg.tobytes())
    except queue.Full:
        pass  # drop old frame — consumer is slow

def _generate_mjpeg():
    while True:
        jpeg = frame_queue.get()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg +
            b"\r\n"
        )

@app.route("/stream")
def stream():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/health")
def health():
    return "ok"

def _start_mjpeg_server(port: int):
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True),
        daemon=True
    ).start()
```

JPEG quality is set to 70 — a good balance between bandwidth and visual quality for a monitoring stream.

### Frontend Consumption

```tsx
// LiveFeed.tsx
<img
  src={streamUrl}                  // NEXT_PUBLIC_STREAM_URL
  alt="Live feed"
  onLoad={() => setStatus("live")}
  onError={() => {
    setStatus("error")
    setTimeout(() => setStatus("connecting"), 3000)
  }}
/>
```

The browser handles MJPEG natively — the `<img>` tag keeps the HTTP connection open and renders each JPEG part as it arrives. No WebSocket or WebRTC required.

---

## 5. Database Layer

### Schema

```sql
CREATE TABLE IF NOT EXISTS detections (
    id             BIGSERIAL PRIMARY KEY,
    timestamp      TIMESTAMPTZ NOT NULL,
    frame_number   INTEGER NOT NULL,
    person_count   INTEGER NOT NULL,
    confidences    JSONB,
    bounding_boxes JSONB,
    count_in       INTEGER NOT NULL DEFAULT 0,
    count_out      INTEGER NOT NULL DEFAULT 0
);
```

### Python Insert (psycopg2)

```python
import psycopg2, json
from datetime import datetime, timezone

def connect_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL,
            frame_number INTEGER NOT NULL,
            person_count INTEGER NOT NULL,
            confidences JSONB,
            bounding_boxes JSONB,
            count_in INTEGER NOT NULL DEFAULT 0,
            count_out INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def insert_detection(conn, frame_num, person_count, confidences, boxes, in_delta, out_delta):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO detections
           (timestamp, frame_number, person_count, confidences, bounding_boxes, count_in, count_out)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            datetime.now(timezone.utc),
            frame_num,
            person_count,
            json.dumps(confidences),
            json.dumps(boxes),
            in_delta,
            out_delta,
        )
    )
    conn.commit()
```

### Node.js Query Pool (pg)

```typescript
// frontend/src/lib/db.ts
import { Pool } from "pg"

declare global {
  var _pgPool: Pool | undefined
}

export const pool = globalThis._pgPool ?? new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 1,                // serverless: keep connection count low
  idleTimeoutMillis: 30_000,
})

globalThis._pgPool = pool
```

The `globalThis` pattern prevents creating a new pool on every Next.js hot-reload during development.

---

## 6. Frontend Dashboard

### page.tsx — Dashboard Shell

```
┌──────────────────────────────────────────────────────┐
│  Header: "EarthCam • Temple Bar"  [Live indicator]   │
├──────────────────────────────────────────────────────┤
│  [Now: 7]  [Today In: 142]  [Today Out: 138]  ...   │  ← MetricCard ×6
├─────────────────────────┬────────────────────────────┤
│  LiveFeed               │  DetectionChart             │
│  (MJPEG <img>)          │  (Recharts AreaChart)       │
├─────────────────────────┴────────────────────────────┤
│  RecentTable (last 10 detections)                    │
├──────────────────────────────────────────────────────┤
│  Footer                                              │
└──────────────────────────────────────────────────────┘
```

Polling logic:

```typescript
useEffect(() => {
  const fetchAll = async () => {
    const [metricsRes, detectionsRes] = await Promise.all([
      fetch("/api/metrics"),
      fetch("/api/detections"),
    ])
    setMetrics(await metricsRes.json())
    setDetections(await detectionsRes.json())
  }
  fetchAll()
  const interval = setInterval(fetchAll, 5_000)
  return () => clearInterval(interval)
}, [])
```

### MetricCard.tsx

```tsx
interface MetricCardProps {
  label: string
  value: string | number
  icon: React.ReactNode
  accent?: "green" | "cyan" | "white"
  loading?: boolean
}
```

Uses Tailwind for glow shadow effects:
- `shadow-[0_0_20px_rgba(0,255,136,0.3)]` — green glow
- `shadow-[0_0_20px_rgba(0,212,255,0.3)]` — cyan glow

### DetectionChart.tsx

```tsx
// Recharts AreaChart — last 60 data points
<AreaChart data={chartData}>
  <defs>
    <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.3} />
      <stop offset="95%" stopColor="#00ff88" stopOpacity={0}   />
    </linearGradient>
  </defs>
  <Area type="monotone" dataKey="person_count" stroke="#00ff88" fill="url(#grad)" />
</AreaChart>
```

### RecentTable.tsx

Confidence badge colour logic:

```typescript
const badgeClass = (conf: number) =>
  conf >= 0.7 ? "text-green-400 bg-green-400/10"
  : conf >= 0.5 ? "text-cyan-400 bg-cyan-400/10"
  : "text-amber-400 bg-amber-400/10"
```

---

## 7. API Routes

### GET /api/metrics

```typescript
// frontend/src/app/api/metrics/route.ts
const { rows } = await pool.query(`
  SELECT
    (SELECT person_count FROM detections ORDER BY timestamp DESC LIMIT 1)  AS current_count,
    (SELECT COALESCE(SUM(count_in),  0) FROM detections WHERE timestamp >= CURRENT_DATE) AS total_today,
    (SELECT COALESCE(SUM(count_out), 0) FROM detections WHERE timestamp >= CURRENT_DATE) AS total_today_out,
    (SELECT COALESCE(SUM(count_in),  0) FROM detections WHERE timestamp >= DATE_TRUNC('month', NOW())) AS total_month,
    (SELECT COALESCE(SUM(count_in),  0) FROM detections) AS total_all_time,
    (SELECT COALESCE(MAX(person_count), 0) FROM detections WHERE timestamp >= CURRENT_DATE) AS peak_today,
    (SELECT COUNT(*) FROM detections WHERE timestamp >= CURRENT_DATE) AS frames_today
`)
return NextResponse.json(rows[0])
```

Response shape:
```json
{
  "current_count": 7,
  "total_today": 142,
  "total_today_out": 138,
  "total_month": 3821,
  "total_all_time": 18440,
  "peak_today": 23,
  "frames_today": 34218
}
```

### GET /api/detections

```typescript
// frontend/src/app/api/detections/route.ts
const chart  = await pool.query(`SELECT timestamp, person_count FROM detections ORDER BY timestamp DESC LIMIT 60`)
const recent = await pool.query(`SELECT * FROM detections ORDER BY timestamp DESC LIMIT 10`)
return NextResponse.json({ chart: chart.rows.reverse(), recent: recent.rows })
```

### GET /api/latest

```typescript
// frontend/src/app/api/latest/route.ts
const { rows } = await pool.query(`SELECT * FROM detections ORDER BY timestamp DESC LIMIT 1`)
return NextResponse.json(rows[0] ?? null)
```

---

## 8. Configuration Reference

### bytetrack_custom.yaml

```yaml
tracker_type: bytetrack
track_high_thresh: 0.5   # Primary detection pool threshold
track_low_thresh: 0.1    # Secondary detection pool threshold
new_track_thresh: 0.6    # Threshold to confirm as a new unique track
track_buffer: 60         # Frames to keep a lost track before deletion
match_thresh: 0.8        # IoU threshold for track-detection matching
fuse_score: True         # Multiply IoU by detection score in cost matrix
```

**Tuning guidance:**
- Crowded scenes → lower `match_thresh` (0.6–0.7) to allow more generous matching
- Frequent ID switches → raise `track_buffer` (up to 120 for ~4s buffer at 30fps)
- Too many false tracks → raise `new_track_thresh` (0.7+)

### tailwind.config.ts — Custom Theme

```typescript
extend: {
  colors: {
    neon: {
      green: "#00ff88",
      cyan:  "#00d4ff",
    }
  },
  animation: {
    "fade-in":    "fadeIn 0.5s ease-in-out",
    "slide-up":   "slideUp 0.3s ease-out",
    "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
  }
}
```

---

## 9. Docker & CI/CD

### Dockerfile

```dockerfile
FROM python:3.12-slim

# System deps: OpenCV needs libgl1, Postgres needs libpq-dev
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 ffmpeg libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY detection.py bytetrack_custom.yaml ./
# yolov8n.pt is downloaded automatically by ultralytics on first run
# or mount it as a volume to avoid re-downloading

CMD ["python", "detection.py", "--no-display"]
```

### docker-compose.yml

```yaml
version: "3.9"
services:
  detector:
    build: .
    env_file: .env
    environment:
      - YOUTUBE_URL=${YOUTUBE_URL}
      - YOLO_MODEL=${YOLO_MODEL:-yolov8n.pt}
      - CONF_THRESHOLD=${CONF_THRESHOLD:-0.40}
      - MJPEG_PORT=8080
    ports:
      - "8080:8080"
    restart: unless-stopped
    volumes:
      - ./yolov8n.pt:/app/yolov8n.pt:ro   # mount pre-downloaded weights
```

### CI Pipeline — ci.yml

```yaml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff
      - run: ruff check detection.py
      - run: ruff format --check detection.py
      - run: python -m py_compile detection.py
```

### Docker Pipeline — docker.yml

```yaml
name: Docker
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=sha
            type=raw,value=latest,enable={{is_default_branch}}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## 10. Extending the System

### Swap to a Different Camera / Stream

1. Obtain the new YouTube live stream URL
2. Recalibrate counting line: run with `--line-pos 0.4` etc. until the line aligns with the pavement edge or doorway
3. Update `YOUTUBE_URL` in `.env`

### Use a Larger YOLO Model

```bash
# Download YOLOv8s weights
python -c "from ultralytics import YOLO; YOLO('yolov8s.pt')"

# Run with larger model
python detection.py --url "..." --model yolov8s.pt --conf 0.45
```

### Add Heatmap Logging

Store centroid positions per frame in a JSONB column:

```sql
ALTER TABLE detections ADD COLUMN centroids JSONB;
```

Insert centroids alongside existing data, then query aggregate positions to generate a heatmap overlay.

### Add Multiple Counting Lines

The current architecture supports one line. To support multiple zones (e.g., two doorways), extend the crossing logic to iterate over a list of `(pos, axis, label)` tuples and log per-zone counts as separate columns or a JSONB map.

### Add Alerts

Use Supabase's Edge Functions or a separate worker to watch for threshold crossings:

```sql
-- Alert if occupancy > 50 for more than 60 seconds
SELECT timestamp, person_count
FROM detections
WHERE person_count > 50
  AND timestamp > NOW() - INTERVAL '60 seconds'
ORDER BY timestamp
```

Trigger a webhook or send an email via SendGrid when this query returns rows.

### Deploy Frontend to Vercel

1. Push `frontend/` to GitHub
2. Connect repo to Vercel — set root directory to `frontend`
3. Set environment variables in Vercel dashboard:
   - `DATABASE_URL` → Supabase **Transaction Pooler** URL (port 6543)
   - `NEXT_PUBLIC_STREAM_URL` → `https://your-vps-domain.com/stream`
4. Deploy

---

## 11. Troubleshooting

### `ffmpeg: command not found`

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Or set FFMPEG_BIN env var to full path
export FFMPEG_BIN=/opt/homebrew/bin/ffmpeg
```

### YOLOv8n weights not found

On first run, Ultralytics auto-downloads `yolov8n.pt` from the internet. If in an airgapped environment, copy `yolov8n.pt` manually into the working directory.

### `psycopg2.OperationalError: could not connect to server`

- Check `DATABASE_URL` is set correctly in `.env`
- Verify Supabase project is active (free tier pauses after 1 week of inactivity)
- Test connectivity: `psql $DATABASE_URL -c "SELECT 1"`

### Stream stays on "Connecting" in browser

- Verify detection backend is running: `curl http://localhost:8080/health` should return `ok`
- Check `NEXT_PUBLIC_STREAM_URL` in `frontend/.env.local` matches the backend port
- If running in Docker, ensure port 8080 is published: `-p 8080:8080`

### Counts seem too high (false positives)

- Raise `CONF_THRESHOLD` to `0.50` or `0.55`
- Raise `MIN_TRACK_AGE` to `5`
- Raise `new_track_thresh` in `bytetrack_custom.yaml` to `0.65`

### Counts seem too low (missed crossings)

- Lower `CONF_THRESHOLD` to `0.30` (watch for false positives)
- Lower `track_high_thresh` in `bytetrack_custom.yaml` to `0.4`
- Check counting line position — if pedestrians don't pass through it, set `--line-pos` closer to where they walk

### Supabase connection exhaustion on Vercel

Switch `DATABASE_URL` in Vercel to the **Transaction Pooler** (PgBouncer) connection string:

```
postgresql://postgres.YOUR_PROJECT:PASSWORD@aws-0-eu-west-1.pooler.supabase.com:6543/postgres
```

This is in Supabase dashboard → Project Settings → Database → Connection String → Transaction Pooler.

### Docker image can't pull ghcr.io image

Ensure the package visibility is set to **Public** in GitHub repository settings → Packages, or authenticate:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```
