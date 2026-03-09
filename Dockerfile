FROM python:3.12-slim

# System deps for OpenCV headless + yt-dlp + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY detection.py .

# DATABASE_URL and YOUTUBE_URL must be supplied at runtime via -e or docker-compose
CMD ["python", "detection.py", "--no-display"]
