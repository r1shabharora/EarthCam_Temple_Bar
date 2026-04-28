# EarthCam — Temple Bar Live Footfall Counter

Real-time person detection and footfall counting system for YouTube live streams, built with YOLOv8, ByteTrack, and a Next.js dashboard. Monitors pedestrian traffic at Temple Bar, Dublin.

---

## What It Does

- Pulls a YouTube live stream via `yt-dlp` + FFmpeg
- Detects and tracks persons in real time using YOLOv8n + ByteTrack
- Counts individuals crossing a configurable virtual line (entries and exits)
- Serves annotated frames as an MJPEG stream
- Logs every second to a Supabase PostgreSQL database
- Displays live metrics and video on a Next.js dashboard

---

## Architecture Overview

```
YouTube Live Stream
        │
        ▼
   yt-dlp (resolve HLS URL)
        │
        ▼
   FFmpeg subprocess (raw BGR frames)
        │
        ▼
   YOLOv8n (person detection, class 0)
        │
        ▼
   ByteTrack (multi-object tracking)
        │
        ▼
   Virtual Line Crossing Logic
   (IN / OUT counts per track)
        │
        ├──► MJPEG Server (Flask :8080/stream)
        │         │
        │         ▼
        │    Browser <img> tag (LiveFeed.tsx)
        │
        └──► Supabase PostgreSQL
                  │
                  ▼
             Next.js API Routes
                  │
                  ▼
             Dashboard (page.tsx)
```

---

## Repository Structure

```
EarthCam/
├── detection.py               # Python backend — detection, tracking, logging, MJPEG
├── requirements.txt           # Python dependencies
├── bytetrack_custom.yaml      # ByteTrack tracker configuration
├── Dockerfile                 # Container for detection.py
├── docker-compose.yml         # Local orchestration
├── .env                       # Backend secrets (DATABASE_URL) — not in git
├── yolov8n.pt                 # YOLOv8 Nano weights (6.5 MB)
│
├── frontend/                  # Next.js 14 dashboard
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx           # Main dashboard page
│   │   │   ├── layout.tsx         # Root layout
│   │   │   ├── globals.css        # Dark theme, animations
│   │   │   └── api/
│   │   │       ├── metrics/route.ts    # GET /api/metrics
│   │   │       ├── detections/route.ts # GET /api/detections
│   │   │       └── latest/route.ts     # GET /api/latest
│   │   ├── components/
│   │   │   ├── LiveFeed.tsx       # MJPEG stream viewer
│   │   │   ├── MetricCard.tsx     # Stat display card
│   │   │   ├── DetectionChart.tsx # Time-series chart (Recharts)
│   │   │   └── RecentTable.tsx    # Recent detections table
│   │   └── lib/
│   │       └── db.ts              # PostgreSQL pool singleton (pg)
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── next.config.mjs
│   └── .env.local                 # Frontend secrets — not in git
│
└── .github/
    └── workflows/
        ├── ci.yml             # Lint + syntax check (ruff, py_compile)
        └── docker.yml         # Build & push to ghcr.io
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- FFmpeg installed and on PATH
- A Supabase project (or any PostgreSQL database)
- A YouTube live stream URL

### 1. Clone & configure

```bash
git clone git@github-r1shabharora:r1shabharora/EarthCam_Temple_Bar.git
cd EarthCam_Temple_Bar
```

Create `.env` in the root:

```env
DATABASE_URL=postgresql://postgres:PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres
```

Create `frontend/.env.local`:

```env
DATABASE_URL=postgresql://postgres:PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres
NEXT_PUBLIC_STREAM_URL=http://localhost:8080/stream
```

### 2. Run the detection backend

```bash
pip install -r requirements.txt
python detection.py --url "https://www.youtube.com/watch?v=LIVE_STREAM_ID"
```

Optional flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--no-display` | off | Disable local OpenCV window |
| `--model` | yolov8n.pt | YOLO model file |
| `--conf` | 0.40 | Detection confidence threshold |
| `--port` | 8080 | MJPEG server port |
| `--line-pos` | 0.5 | Counting line position (0.0–1.0) |
| `--line-axis` | x | Line orientation: `x` (vertical) or `y` (horizontal) |

### 3. Run the frontend dashboard

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 4. Docker (backend only)

```bash
docker-compose up
```

---

## Database Schema

```sql
CREATE TABLE detections (
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

The table is auto-created on first run if it does not exist.

---

## API Routes

### Backend (Flask)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stream` | GET | MJPEG annotated video stream |
| `/health` | GET | Health check — returns `"ok"` |

### Frontend (Next.js)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics` | GET | Current count, today/month/all-time totals, peak |
| `/api/detections` | GET | Chart data (last 60s) + recent detections table |
| `/api/latest` | GET | Most recent frame's detection data |

---

## Environment Variables

### Backend (`detection.py`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `YOUTUBE_URL` | If no `--url` | — | YouTube live stream URL |
| `YOLO_MODEL` | No | yolov8n.pt | YOLO weights file |
| `CONF_THRESHOLD` | No | 0.40 | Detection confidence |
| `FFMPEG_BIN` | No | ffmpeg | Path to FFmpeg binary |
| `MJPEG_PORT` | No | 8080 | MJPEG server port |
| `COUNT_LINE_POS` | No | 0.5 | Counting line position |
| `COUNT_LINE_AXIS` | No | x | Counting line axis |
| `MIN_TRACK_AGE` | No | 3 | Frames before counting crossings |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `NEXT_PUBLIC_STREAM_URL` | Yes | URL of the MJPEG stream |

---

## CI/CD

### `ci.yml` — triggered on every push and PR to main

- Lint with `ruff check detection.py`
- Format check with `ruff format --check detection.py`
- Syntax validation with `python -m py_compile detection.py`

### `docker.yml` — triggered on push to main

- Authenticates to GitHub Container Registry (`ghcr.io`)
- Builds Docker image with BuildKit cache
- Pushes with tags:
  - `sha-<commit>` — per commit
  - `latest` — on main branch

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Detection model | YOLOv8 Nano (Ultralytics) |
| Tracker | ByteTrack |
| Stream ingest | yt-dlp + FFmpeg |
| MJPEG server | Flask 3 |
| Database | Supabase PostgreSQL |
| Frontend framework | Next.js 14 (App Router) |
| UI styling | Tailwind CSS |
| Charts | Recharts |
| Icons | Lucide React |
| DB client (Python) | psycopg2-binary |
| DB client (Node) | pg |
| Container | Docker + GitHub Container Registry |

---

## License

Private repository — r1shabharora / EarthCam_Temple_Bar
