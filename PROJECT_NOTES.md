# Project Notes — EarthCam Temple Bar

Internal notes on design decisions, known issues, configuration choices, and operational context.

---

## Project Context

This system monitors pedestrian footfall at Temple Bar, Dublin, using a publicly available YouTube live stream. The goal is to produce accurate IN/OUT counts and a real-time occupancy estimate without any dedicated sensor hardware.

The system is designed to run continuously (24/7) with automatic stream reconnection. All data is persisted to Supabase so the dashboard can be served independently of the detection backend.

---

## Counting Methodology

### Why Virtual Line Crossing?

Virtual line crossing is the industry-standard approach used by Axis Communications, Bosch, Hikvision, Verkada, and RetailNext for retail/public space footfall counting. It is preferred over simple person-count snapshots because:

- **Snapshot counting** double-counts stationary people and undercounts moving people
- **Line crossing** counts unique traversal events, giving true entry/exit volumes
- Works correctly even with occlusions and re-identifications (ByteTrack handles this)

### Algorithm

1. For each tracked person, compute their **foot point** — the bottom-centre of the bounding box `(x1+x2)/2, y2`
2. Each frame, determine which **side** of the counting line the foot point is on:
   - For a vertical line at position `p` (fraction of frame width): side = `+1` if `foot_x > p * W`, else `-1`
   - For a horizontal line at position `p` (fraction of frame height): side = `+1` if `foot_y > p * H`, else `-1`
3. When the side changes between frames for the same track ID:
   - `-1 → +1`: **IN** event (crossing left-to-right or top-to-bottom)
   - `+1 → -1`: **OUT** event (crossing right-to-left or bottom-to-top)
4. Only count if `track_age >= MIN_TRACK_AGE` (default 3 frames) to prevent false counts from noisy detections

### MIN_TRACK_AGE Gate

Without this gate, short-lived spurious detections (often on frame boundaries or with motion blur) can generate phantom crossing events. Setting `MIN_TRACK_AGE = 3` means a track must be confirmed across 3 consecutive frames before any crossing it performs is counted.

### Counting Line Configuration

- **Position** (`COUNT_LINE_POS`): fraction of frame dimension, default `0.5` (centre)
- **Axis** (`COUNT_LINE_AXIS`): `x` = vertical line (counts left/right crossing), `y` = horizontal line (counts top/bottom crossing)

For Temple Bar's camera angle (overhead/angled view from the side of the street), a **vertical line** (`axis=x`) at the frame centre works well.

---

## Model Choice — YOLOv8 Nano

`yolov8n.pt` (6.5 MB, ~3.2M parameters) is used deliberately:

| Model | Size | CPU FPS | GPU FPS |
|-------|------|---------|---------|
| YOLOv8n | 6.5 MB | ~25 fps | ~200 fps |
| YOLOv8s | 22 MB | ~12 fps | ~100 fps |
| YOLOv8m | 52 MB | ~6 fps | ~60 fps |

For this use case, real-time throughput on CPU matters more than marginal accuracy gains. At 0.4 confidence threshold, Nano gives acceptable precision for person detection in outdoor scenes.

If run on a machine with a CUDA GPU, YOLOv8 will automatically use it — no code change required.

---

## ByteTrack Configuration Notes

File: `bytetrack_custom.yaml`

```yaml
track_high_thresh: 0.5   # Min confidence to create a primary track
track_low_thresh:  0.1   # Secondary pool threshold (low-conf detections)
new_track_thresh:  0.6   # Confirmation threshold for a new track ID
track_buffer: 60         # Frames to keep a lost track alive (~2s at 30fps)
match_thresh: 0.8        # IoU threshold for matching tracks to detections
fuse_score: True         # Fuse detection score with IoU in cost matrix
```

`track_buffer: 60` is important — it allows re-identification of a person who was briefly occluded (e.g., behind a bus) without assigning them a new track ID, which would double-count.

---

## Database Logging Rate

The system logs **one row per second** regardless of frame rate. This is intentional:

- At 25 fps, logging every frame would be 25× more writes with no meaningful extra resolution for a footfall dashboard
- 1 row/sec = 86,400 rows/day → manageable Supabase storage and query times
- The `chart` query fetches the last 60 rows for the time-series graph (last ~60 seconds)

Supabase free tier allows up to 500 MB of database storage. At ~200 bytes/row average (JSON included), 86,400 rows/day ≈ 17 MB/day. **Monthly storage ≈ 510 MB** — monitor and add retention policies if needed.

---

## Stream Reconnection Behaviour

`detection.py` handles stream failures with exponential backoff:

1. On stream EOF or FFmpeg pipe death → attempt to re-resolve the YouTube URL and reopen FFmpeg
2. Backoff sequence: 5s → 10s → 20s → 40s → ... (capped at ~5 minutes)
3. DB connection is also re-established on failure before inserting

YouTube live streams occasionally rotate the HLS manifest URL. `yt-dlp` re-resolves this on each reconnect automatically.

---

## MJPEG Stream Design

The annotated video is served as an MJPEG stream (`multipart/x-mixed-replace`) via Flask running on a background thread. The frontend `<img>` tag natively handles MJPEG in all modern browsers without JavaScript polling.

Frame queue: Flask pulls from a thread-safe queue. If the consumer (browser) is slow, old frames are dropped to avoid memory buildup (`maxsize=1` queue).

Port default: **8080**. This must be reachable from the browser. In local dev, both services run on the same machine. In production, the MJPEG URL (`NEXT_PUBLIC_STREAM_URL`) must point to the publicly accessible backend host.

---

## Known Issues & Limitations

### 1. YouTube Stream Availability
YouTube live streams can go offline unexpectedly (maintenance, copyright, connectivity). The system will retry indefinitely, but counts will have gaps in the database during outages.

### 2. Camera Angle Dependency
The counting line position (`COUNT_LINE_POS`) is calibrated for the current Temple Bar camera angle. If the stream changes camera, the line may need repositioning.

### 3. Night-time Accuracy Drop
YOLOv8 person detection accuracy degrades significantly in low-light conditions. Confidence threshold may need lowering at night, at the cost of more false positives.

### 4. No Authentication on MJPEG Endpoint
`/stream` is unauthenticated. In production, it should be behind a reverse proxy (nginx) with basic auth or IP allowlisting if publicly exposed.

### 5. Supabase Serverless Connections
The Next.js frontend API routes run in serverless mode on Vercel. Each invocation creates a new PostgreSQL connection. The `db.ts` file uses a module-level pool singleton, but in serverless environments each cold start creates a new pool. Use the **Supabase Transaction Pooler** (PgBouncer) connection string (`port 6543`) for Vercel deployments to avoid connection exhaustion.

### 6. No Historical Replay
The system only processes live frames. There is no facility to process recorded footage retrospectively. All historical data comes from what was logged during live operation.

---

## Operational Notes

### Running 24/7

For continuous operation, use a process supervisor:

```bash
# systemd service (Linux)
sudo systemctl enable earthcam-detector

# Or via Docker with restart policy
docker run --restart unless-stopped ...
```

### Monitoring Console Output

The detection script logs a summary line every second:

```
2024-01-15 14:32:01 | Frame 84301 | Persons: 7 | IN: 142 | OUT: 138
```

Pipe to a log file in production:

```bash
python detection.py --url "..." --no-display >> /var/log/earthcam.log 2>&1
```

### Database Retention

Consider adding a cron job or Supabase scheduled function to archive or delete rows older than 90 days:

```sql
DELETE FROM detections WHERE timestamp < NOW() - INTERVAL '90 days';
```

---

## Deployment Topology

### Local Development

```
Macbook
  ├── detection.py (Python, :8080)
  └── next dev (Node, :3000)
      └── both connect to Supabase directly
```

### Production (Recommended)

```
VPS / Cloud VM
  └── Docker container (detection.py, :8080)
      └── nginx reverse proxy (optional auth)
          └── exposed publicly or via VPN

Vercel
  └── Next.js frontend
      └── NEXT_PUBLIC_STREAM_URL → VPS:8080/stream
      └── DATABASE_URL → Supabase Transaction Pooler (:6543)
```

---

## Data Flow Summary

```
YouTube HLS
    │  yt-dlp resolves manifest URL
    ▼
FFmpeg pipe → raw BGR bytes → numpy array
    │
    ▼
YOLOv8n inference → boxes[], confidences[], class_ids[]
    │
    ▼
ByteTrack → tracked_objects[]{track_id, box, age}
    │
    ├── For each track:
    │     foot_point = (cx, y2)
    │     side = sign(foot_x - line_x)  [or y equivalent]
    │     if prev_side != side and age >= MIN_TRACK_AGE:
    │         count_in++ or count_out++
    │
    ├── draw_frame() → annotated BGR frame
    │     └── JPEG encode → MJPEG queue → Flask /stream
    │
    └── Every 1 second:
          insert_detection(timestamp, frame_num, person_count,
                           confidences, bounding_boxes,
                           delta_in, delta_out)
              └── Supabase PostgreSQL (detections table)
```
