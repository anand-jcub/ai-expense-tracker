# Phase 0: run classic UI + APIs in one container (SQLite on DATA_DIR volume).
# Build:  docker build -t expense-tracker .
# Run:    docker run --rm -p 8080:8080 -e PORT=8080 -v expensedata:/data -e DATA_DIR=/data expense-tracker

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    DATA_DIR=/data \
    ENV=production \
    COOKIE_SECURE=1

WORKDIR /app

# System deps for pdfplumber/pypdfium2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY expense_tracker ./expense_tracker
COPY frontend/dist ./frontend/dist

# Optional: empty data dir; mount a volume over /data in production
RUN mkdir -p /data

EXPOSE 8080

# Cloud Run / Fly inject PORT; app reads HOST/PORT/DATA_DIR
CMD ["python", "app.py"]
