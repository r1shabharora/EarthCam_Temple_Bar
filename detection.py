"""
Person Detection System — YouTube Live Feed
Detects, counts, and labels persons using YOLOv8.
Logs results to a CSV file with timestamps.

Usage:
    python detection.py --url "https://www.youtube.com/watch?v=XXXX"
    python detection.py --url "https://www.youtube.com/watch?v=XXXX" --no-display

Environment variables (Docker / CI):
    YOUTUBE_URL     YouTube live stream URL (alternative to --url)
    YOLO_MODEL      Model file name (default: yolov8n.pt)
    CONF_THRESHOLD  Detection confidence 0-1 (default: 0.40)
    CSV_PATH        Output CSV path (default: detections.csv)
"""

import argparse
import csv
import os
import subprocess
import time
from datetime import datetime

import cv2
from ultralytics import YOLO

# ── Config (overridable via environment variables) ───────────────────────────
YOLO_MODEL      = os.getenv("YOLO_MODEL", "yolov8n.pt")
PERSON_CLASS_ID = 0                                        # COCO class 0 = person
CONF_THRESHOLD  = float(os.getenv("CONF_THRESHOLD", "0.40"))
LOG_INTERVAL_S  = 1.0                                      # CSV rows at most once/sec
CSV_PATH        = os.getenv("CSV_PATH", "detections.csv")


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_stream_url(youtube_url: str) -> str:
    """Use yt-dlp to resolve the best available stream URL."""
    print(f"[INFO] Resolving stream URL for: {youtube_url}")
    result = subprocess.run(
        [
            "yt-dlp",
            "--no-warnings",
            "-f", "best[ext=mp4]/best",
            "--get-url",
            youtube_url,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr.strip()}")
    url = result.stdout.strip().splitlines()[0]
    print(f"[INFO] Stream URL resolved.")
    return url


def init_csv(path: str) -> csv.writer:
    """Open (or append to) the CSV log file and return a writer."""
    file_exists = os.path.isfile(path)
    f = open(path, "a", newline="")
    writer = csv.writer(f)
    if not file_exists:
        writer.writerow([
            "timestamp",
            "frame_number",
            "person_count",
            "confidences",          # comma-separated confidence scores
            "bounding_boxes",       # list of [x1,y1,x2,y2] per person
        ])
        f.flush()
    return writer, f


def draw_detections(frame, boxes, confidences):
    """Draw bounding boxes and labels on the frame in-place."""
    for i, (box, conf) in enumerate(zip(boxes, confidences), start=1):
        x1, y1, x2, y2 = map(int, box)
        label = f"Person {i}  {conf:.0%}"

        # Box
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)

        # Label background
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), (0, 200, 0), -1)

        # Label text
        cv2.putText(
            frame, label,
            (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (0, 0, 0), 1, cv2.LINE_AA,
        )

    # Count overlay (top-left)
    count_text = f"Persons detected: {len(boxes)}"
    cv2.putText(
        frame, count_text,
        (10, 32),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
        (0, 200, 0), 2, cv2.LINE_AA,
    )

    # Timestamp overlay (bottom-left)
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(
        frame, ts,
        (10, frame.shape[0] - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
        (200, 200, 200), 1, cv2.LINE_AA,
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def run(youtube_url: str, display: bool = True):
    # 1. Load model
    print(f"[INFO] Loading YOLO model: {YOLO_MODEL}")
    model = YOLO(YOLO_MODEL)

    # 2. Resolve stream
    stream_url = get_stream_url(youtube_url)

    # 3. Open video capture
    print("[INFO] Opening video stream …")
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video stream. Check the URL or your network.")

    # 4. Set up CSV
    writer, csv_file = init_csv(CSV_PATH)
    print(f"[INFO] Logging detections → {CSV_PATH}")
    print("[INFO] Press  q  to quit.\n")

    frame_num   = 0
    last_log_ts = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Frame not received — stream may have ended or buffered.")
                time.sleep(0.5)
                continue

            frame_num += 1

            # 5. Run inference (only class 0 = person)
            results = model(
                frame,
                classes=[PERSON_CLASS_ID],
                conf=CONF_THRESHOLD,
                verbose=False,
            )[0]

            boxes       = results.boxes.xyxy.cpu().numpy().tolist()   # [[x1,y1,x2,y2], …]
            confidences = results.boxes.conf.cpu().numpy().tolist()   # [0.91, 0.87, …]
            count       = len(boxes)

            # 6. Log to CSV (rate-limited)
            now = time.time()
            if now - last_log_ts >= LOG_INTERVAL_S:
                last_log_ts = now
                ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conf_str = ";".join(f"{c:.3f}" for c in confidences)
                box_str  = ";".join(
                    f"[{int(b[0])},{int(b[1])},{int(b[2])},{int(b[3])}]"
                    for b in boxes
                )
                writer.writerow([ts_str, frame_num, count, conf_str, box_str])
                csv_file.flush()

                print(
                    f"[{ts_str}]  frame={frame_num:>6}  persons={count}  "
                    + (f"conf=[{conf_str}]" if count else "")
                )

            # 7. Draw + display
            if display:
                draw_detections(frame, boxes, confidences)
                cv2.imshow("Person Detection — EarthCam", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("[INFO] Quit requested.")
                    break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        cap.release()
        csv_file.close()
        if display:
            cv2.destroyAllWindows()
        print(f"[INFO] Detection log saved → {CSV_PATH}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Person detection on a YouTube live stream.")
    parser.add_argument(
        "--url",
        default=os.getenv("YOUTUBE_URL"),
        help="YouTube live stream URL (or set YOUTUBE_URL env var)",
    )
    parser.add_argument("--no-display", action="store_true",
                        help="Run headless (no OpenCV window)")
    parser.add_argument("--model",      default=YOLO_MODEL,
                        help=f"YOLO model file (default: {YOLO_MODEL})")
    parser.add_argument("--conf",       type=float, default=CONF_THRESHOLD,
                        help=f"Confidence threshold (default: {CONF_THRESHOLD})")
    parser.add_argument("--output",     default=CSV_PATH,
                        help=f"CSV output path (default: {CSV_PATH})")
    args = parser.parse_args()

    if not args.url:
        parser.error("Provide --url or set the YOUTUBE_URL environment variable.")

    YOLO_MODEL      = args.model
    CONF_THRESHOLD  = args.conf
    CSV_PATH        = args.output

    run(youtube_url=args.url, display=not args.no_display)
