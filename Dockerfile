FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Zależności
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY uploads ./uploads
COPY migrations ./migrations

# Port i start
ENV PORT=8080
EXPOSE 8080
CMD ["gunicorn","-w","2","-b","0.0.0.0:8080","--access-logfile","-","--error-logfile","-","wsgi:app"]
