FROM python:3.12-slim

# System deps for OpenCV headless + yt-dlp
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY detection.py .

# CSV output lives in a mounted volume: docker run -v $(pwd)/data:/app/data ...
ENV CSV_PATH=/app/data/detections.csv

# YOUTUBE_URL must be supplied at runtime via -e or docker-compose
CMD ["python", "detection.py", "--no-display"]
