FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Zależności
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY uploads ./uploads
COPY migrations ./migrations
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

# Flask CLI needs this
ENV FLASK_APP=backend.app

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "backend.wsgi:app"]
