FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt && useradd --create-home --uid 10001 app

COPY backend ./backend
COPY frontend ./frontend
COPY data/rules.json ./data/rules.json

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# Sessions are in-process: keep one worker per container (scale out with replicas + sticky sessions,
# or move sessions to Redis — see docs/SCALING.md). Secrets come from the platform's env, never the image.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--no-server-header"]
