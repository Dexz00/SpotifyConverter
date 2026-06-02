FROM python:3.11-slim

# ffmpeg is required to convert/tag the audio; install it from the distro.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY app/ ./app/
COPY web/ ./web/
COPY run.py .

# Listen on all interfaces inside the container.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Optional Spotify API credentials can be passed at runtime:
#   docker run -e SPOTIFY_CLIENT_ID=... -e SPOTIFY_CLIENT_SECRET=... ...
CMD ["python", "run.py"]
