"""
Person Detection System — YouTube Live Feed
Detects, counts, and labels persons using YOLOv8 + ByteTrack.
Counts unique persons via virtual line crossing (industry-standard footfall method).
Logs results to Supabase (PostgreSQL) and streams annotated frames via MJPEG.

Usage:
    python detection.py --url "https://www.youtube.com/watch?v=XXXX"
    python detection.py --url "https://www.youtube.com/watch?v=XXXX" --no-display --port 8080

Environment variables (set in .env or shell):
    DATABASE_URL     Supabase direct connection string (required)
    YOUTUBE_URL      YouTube live stream URL (alternative to --url)
    YOLO_MODEL       Model file name (default: yolov8n.pt)
    CONF_THRESHOLD   Detection confidence 0-1 (default: 0.40)
    FFMPEG_BIN       Path to ffmpeg binary (default: ffmpeg)
    MJPEG_PORT       Port for the MJPEG HTTP server (default: 8080)
    COUNT_LINE_POS   Counting line position as fraction 0.0–1.0 (default: 0.5)
    COUNT_LINE_AXIS  "x" = vertical line (counts left↔right crossings)
                     "y" = horizontal line (counts up↔down crossings) (default: x)
    MIN_TRACK_AGE    Frames a track must exist before its crossings are counted (default: 3)

Counting methodology:
    A virtual counting line is drawn across the frame. The foot-point (bottom-centre)
    of each tracked bounding box is compared to the line each frame. When a tracked
    person's foot-point crosses the line and the track is at least MIN_TRACK_AGE frames
    old, a crossing event is recorded as count_in or count_out depending on direction.
    This is the method used by Axis, Bosch, Hikvision, and RetailNext.

Stream handling:
    yt-dlp resolves the YouTube URL → ffmpeg decodes HLS → raw BGR frames
    are piped into this script, annotated by YOLOv8, then served as MJPEG.
"""

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np
import psycopg2
from dotenv import load_dotenv
from flask import Flask, Response
from ultralytics import YOLO

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
YOLO_MODEL       = os.getenv("YOLO_MODEL", "yolov8n.pt")
PERSON_CLASS_ID  = 0
CONF_THRESHOLD   = float(os.getenv("CONF_THRESHOLD", "0.40"))
LOG_INTERVAL_S   = 1.0
FFMPEG_BIN       = os.getenv("FFMPEG_BIN", "ffmpeg")
DATABASE_URL     = os.getenv("DATABASE_URL")
MJPEG_PORT       = int(os.getenv("MJPEG_PORT", "8080"))

MAX_RECONNECTS    = 20
RECONNECT_DELAY_S = 5

# ── Counting line config ───────────────────────────────────────────────────────
# COUNT_LINE_AXIS="x"  → vertical line; person crosses left↔right (typical street cam)
# COUNT_LINE_AXIS="y"  → horizontal line; person crosses up↔down (typical overhead cam)
COUNT_LINE_POS  = float(os.getenv("COUNT_LINE_POS", "0.5"))
COUNT_LINE_AXIS = os.getenv("COUNT_LINE_AXIS", "x")
MIN_TRACK_AGE   = int(os.getenv("MIN_TRACK_AGE", "3"))

# Colours
NEON  = (0, 255, 136)   # BGR neon green — detections
AMBER = (0, 191, 255)   # BGR amber/gold — counting line & IN label
RED   = (50,  50, 220)  # BGR red        — OUT label

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS detections (
    id                BIGSERIAL    PRIMARY KEY,
    timestamp         TIMESTAMPTZ  NOT NULL,
    frame_number      INTEGER      NOT NULL,
    person_count      INTEGER      NOT NULL,
    confidences       JSONB,
    bounding_boxes    JSONB,
    new_confirmations INTEGER      NOT NULL DEFAULT 0,
    count_in          INTEGER      NOT NULL DEFAULT 0,
    count_out         INTEGER      NOT NULL DEFAULT 0
);
ALTER TABLE detections ADD COLUMN IF NOT EXISTS count_in  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE detections ADD COLUMN IF NOT EXISTS count_out INTEGER NOT NULL DEFAULT 0;
"""

# ── MJPEG server ──────────────────────────────────────────────────────────────
_frame_slot: queue.Queue = queue.Queue(maxsize=1)
_flask_app = Flask(__name__)


def _push_jpeg(frame_bgr: np.ndarray, quality: int = 75) -> None:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return
    data = buf.tobytes()
    if _frame_slot.full():
        try:
            _frame_slot.get_nowait()
        except queue.Empty:
            pass
    try:
        _frame_slot.put_nowait(data)
    except queue.Full:
        pass


def _generate_mjpeg():
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    while True:
        try:
            jpeg = _frame_slot.get(timeout=2.0)
        except queue.Empty:
            continue
        yield boundary + jpeg + b"\r\n"


@_flask_app.route("/stream")
def mjpeg_stream():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@_flask_app.route("/health")
def health():
    return "ok"


def _start_mjpeg_server(port: int) -> None:
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"[INFO] MJPEG stream → http://0.0.0.0:{port}/stream")
    _flask_app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


# ── Database ──────────────────────────────────────────────────────────────────

def connect_db() -> psycopg2.extensions.connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(TABLE_DDL)
    print("[INFO] Connected to Supabase — table 'detections' ready.")
    return conn


def insert_detection(conn, frame_num: int, count: int, confidences: list,
                     boxes: list, count_in: int = 0, count_out: int = 0):
    ts         = datetime.now(timezone.utc)
    confs_json = json.dumps([round(c, 3) for c in confidences])
    boxes_json = json.dumps([
        {"x1": int(b[0]), "y1": int(b[1]), "x2": int(b[2]), "y2": int(b[3])}
        for b in boxes
    ])
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO detections
              (timestamp, frame_number, person_count, confidences, bounding_boxes,
               count_in, count_out)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (ts, frame_num, count, confs_json, boxes_json, count_in, count_out),
        )


# ── Stream helpers ────────────────────────────────────────────────────────────

def get_stream_info(youtube_url: str) -> tuple[str, int, int]:
    print("[INFO] Resolving stream info …")
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "-f", "best", "-j", youtube_url],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr.strip()}")
    info   = json.loads(result.stdout)
    url    = info["url"]
    width  = info.get("width")  or 1920
    height = info.get("height") or 1080
    print(f"[INFO] Stream resolved — {width}x{height}")
    return url, width, height


def open_ffmpeg_pipe(stream_url: str, width: int, height: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            FFMPEG_BIN, "-loglevel", "error",
            "-i", stream_url,
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-an", "pipe:1",
        ],
        stdout=subprocess.PIPE,
        bufsize=width * height * 3 * 4,
    )


def read_frame(proc: subprocess.Popen, width: int, height: int):
    raw = proc.stdout.read(width * height * 3)
    if len(raw) < width * height * 3:
        return False, None
    return True, np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()


# ── Virtual line crossing ─────────────────────────────────────────────────────

def _foot_point(box: list) -> tuple[float, float]:
    """Bottom-centre of a bounding box — more stable than centroid for ground-level cams."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, float(y2))


def _line_side(px: float, py: float, line_coord: float, axis: str) -> int:
    """Returns +1 or -1 depending on which side of the counting line the point is."""
    val = py if axis == "y" else px
    return 1 if val > line_coord else -1


# ── Annotation ────────────────────────────────────────────────────────────────

def draw_frame(frame: np.ndarray, boxes: list, confidences: list,
               track_ids: list | None,
               line_coord: float, axis: str,
               total_in: int, total_out: int) -> None:
    h, w = frame.shape[:2]

    # ── Counting line ──────────────────────────────────────────────────────────
    if axis == "y":
        y = int(line_coord)
        cv2.line(frame, (0, y), (w, y), AMBER, 2, cv2.LINE_AA)
        # Direction arrows
        arrow_x = w // 2
        cv2.arrowedLine(frame, (arrow_x - 40, y), (arrow_x - 40, y - 20), AMBER, 1, tipLength=0.4)
        cv2.arrowedLine(frame, (arrow_x + 40, y), (arrow_x + 40, y + 20), RED,   1, tipLength=0.4)
    else:
        x = int(line_coord)
        cv2.line(frame, (x, 0), (x, h), AMBER, 2, cv2.LINE_AA)
        arrow_y = h // 2
        cv2.arrowedLine(frame, (x, arrow_y - 40), (x - 20, arrow_y - 40), AMBER, 1, tipLength=0.4)
        cv2.arrowedLine(frame, (x, arrow_y + 40), (x + 20, arrow_y + 40), RED,   1, tipLength=0.4)

    # ── Bounding boxes ─────────────────────────────────────────────────────────
    for i, (box, conf) in enumerate(zip(boxes, confidences)):
        x1, y1, x2, y2 = map(int, box)
        tid   = track_ids[i] if track_ids else (i + 1)
        label = f"#{tid}  {conf:.0%}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), NEON, 1)

        tick = max(8, int(min(x2 - x1, y2 - y1) * 0.15))
        for (px, py), (dx, dy) in [
            ((x1, y1), (tick, 0)), ((x1, y1), (0, tick)),
            ((x2, y1), (-tick, 0)), ((x2, y1), (0, tick)),
            ((x1, y2), (tick, 0)), ((x1, y2), (0, -tick)),
            ((x2, y2), (-tick, 0)), ((x2, y2), (0, -tick)),
        ]:
            cv2.line(frame, (px, py), (px + dx, py + dy), NEON, 2)

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ly = y1 - 6 if y1 > th + 10 else y2 + th + 6
        cv2.rectangle(frame, (x1, ly - th - 4), (x1 + tw + 8, ly + 2), (0, 0, 0), -1)
        cv2.putText(frame, label, (x1 + 4, ly - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, NEON, 1, cv2.LINE_AA)

    # ── HUD — top-left ─────────────────────────────────────────────────────────
    hud_lines = [
        (f"  NOW: {len(boxes)}", NEON),
        (f"  IN:  {total_in}",   AMBER),
        (f"  OUT: {total_out}",  RED),
    ]
    for row, (txt, col) in enumerate(hud_lines):
        y0 = 28 + row * 26
        cv2.rectangle(frame, (0, y0 - 20), (170, y0 + 6), (0, 0, 0), -1)
        cv2.putText(frame, txt, (4, y0),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 1, cv2.LINE_AA)

    # ── HUD — timestamp ────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S UTC")
    (tsw, _), _ = cv2.getTextSize(ts, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
    cv2.rectangle(frame, (w - tsw - 14, h - 22), (w, h), (0, 0, 0), -1)
    cv2.putText(frame, ts, (w - tsw - 8, h - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1, cv2.LINE_AA)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(youtube_url: str, display: bool = True, mjpeg_port: int = MJPEG_PORT) -> None:
    threading.Thread(target=_start_mjpeg_server, args=(mjpeg_port,), daemon=True).start()

    print(f"[INFO] Loading YOLO model: {YOLO_MODEL}")
    model = YOLO(YOLO_MODEL)
    conn  = connect_db()
    print(f"[INFO] Counting line: axis={COUNT_LINE_AXIS}  pos={COUNT_LINE_POS}")
    print("[INFO] Press  q  to quit.\n")

    frame_num      = 0
    last_log_ts    = 0.0
    quit_requested = False

    # Cumulative session totals (for HUD display)
    session_in  = 0
    session_out = 0

    try:
        for attempt in range(1, MAX_RECONNECTS + 1):
            if quit_requested:
                break

            # ── Tracking state — reset on each (re)connect ────────────────────
            # track_id → number of frames the track has been seen (for MIN_TRACK_AGE gate)
            track_age: dict[int, int] = {}
            # track_id → which side of the counting line it was on last frame (+1 or -1)
            track_prev_side: dict[int, int] = {}

            try:
                stream_url, width, height = get_stream_info(youtube_url)
            except Exception as e:
                print(f"[WARN] Stream setup failed (attempt {attempt}): {e} — retrying in {RECONNECT_DELAY_S}s")
                time.sleep(RECONNECT_DELAY_S)
                continue

            # Pixel coordinate of the counting line
            line_coord = COUNT_LINE_POS * (height if COUNT_LINE_AXIS == "y" else width)

            print(f"[INFO] Opening ffmpeg pipe (attempt {attempt}) …")
            proc = open_ffmpeg_pipe(stream_url, width, height)

            while not quit_requested:
                ret, frame = read_frame(proc, width, height)
                if not ret:
                    print("[WARN] Stream ended — reconnecting …")
                    proc.terminate()
                    proc.wait()
                    break

                frame_num += 1

                # ── YOLO + ByteTrack ──────────────────────────────────────────
                results     = model.track(frame, classes=[PERSON_CLASS_ID],
                                          conf=CONF_THRESHOLD, persist=True,
                                          tracker="bytetrack_custom.yaml",
                                          verbose=False)[0]
                boxes       = results.boxes.xyxy.cpu().numpy().tolist()
                confidences = results.boxes.conf.cpu().numpy().tolist()
                count       = len(boxes)

                raw_ids   = results.boxes.id
                track_ids = (raw_ids.cpu().numpy().astype(int).tolist()
                             if raw_ids is not None else [])

                # ── Virtual line crossing detection ───────────────────────────
                frame_in  = 0
                frame_out = 0

                for i, (box, tid) in enumerate(zip(boxes, track_ids)):
                    track_age[tid] = track_age.get(tid, 0) + 1

                    fx, fy = _foot_point(box)
                    side   = _line_side(fx, fy, line_coord, COUNT_LINE_AXIS)

                    prev_side = track_prev_side.get(tid)

                    if (prev_side is not None
                            and prev_side != side
                            and track_age[tid] >= MIN_TRACK_AGE):
                        # Crossing confirmed — direction: +1→-1 is OUT, -1→+1 is IN
                        if side == 1:
                            frame_in  += 1
                            session_in += 1
                        else:
                            frame_out  += 1
                            session_out += 1

                    track_prev_side[tid] = side

                # ── Annotate & stream ─────────────────────────────────────────
                draw_frame(frame, boxes, confidences,
                           track_ids if track_ids else None,
                           line_coord, COUNT_LINE_AXIS,
                           session_in, session_out)
                _push_jpeg(frame)

                # ── Log to Supabase (rate-limited) ────────────────────────────
                now = time.time()
                if now - last_log_ts >= LOG_INTERVAL_S:
                    last_log_ts = now
                    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        insert_detection(conn, frame_num, count, confidences,
                                         boxes, frame_in, frame_out)
                    except psycopg2.Error as db_err:
                        print(f"[WARN] DB insert failed: {db_err} — reconnecting …")
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = connect_db()

                    cross_str = ""
                    if frame_in:  cross_str += f"  +{frame_in}→IN"
                    if frame_out: cross_str += f"  +{frame_out}→OUT"
                    print(
                        f"[{ts_str}]  frame={frame_num:>6}  persons={count}"
                        + (f"  session in={session_in} out={session_out}" if cross_str else "")
                        + cross_str
                    )

                if display:
                    cv2.imshow("Person Detection — EarthCam", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        print("[INFO] Quit requested.")
                        quit_requested = True

            if not quit_requested:
                time.sleep(RECONNECT_DELAY_S)

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        conn.close()
        if display:
            cv2.destroyAllWindows()
        print(f"[INFO] Session totals — IN: {session_in}  OUT: {session_out}")
        print("[INFO] Done.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Person detection — YouTube live stream.")
    parser.add_argument("--url", default=os.getenv("YOUTUBE_URL"),
                        help="YouTube live stream URL (or set YOUTUBE_URL env var)")
    parser.add_argument("--no-display", action="store_true",
                        help="Skip local OpenCV window (MJPEG stream still runs)")
    parser.add_argument("--model", default=YOLO_MODEL,
                        help=f"YOLO model (default: {YOLO_MODEL})")
    parser.add_argument("--conf", type=float, default=CONF_THRESHOLD,
                        help=f"Confidence threshold (default: {CONF_THRESHOLD})")
    parser.add_argument("--port", type=int, default=MJPEG_PORT,
                        help=f"MJPEG server port (default: {MJPEG_PORT})")
    parser.add_argument("--line-pos", type=float, default=COUNT_LINE_POS,
                        help=f"Counting line position 0.0–1.0 (default: {COUNT_LINE_POS})")
    parser.add_argument("--line-axis", choices=["x", "y"], default=COUNT_LINE_AXIS,
                        help=f"Counting line axis: x=vertical, y=horizontal (default: {COUNT_LINE_AXIS})")
    args = parser.parse_args()

    if not args.url:
        parser.error("Provide --url or set the YOUTUBE_URL environment variable.")

    YOLO_MODEL       = args.model
    CONF_THRESHOLD   = args.conf
    COUNT_LINE_POS   = args.line_pos
    COUNT_LINE_AXIS  = args.line_axis

    run(youtube_url=args.url, display=not args.no_display, mjpeg_port=args.port)
