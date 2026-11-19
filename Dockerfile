FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_DOTENV=1

WORKDIR /app
RUN adduser --disabled-password --gecos "" appuser
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY --chown=appuser:appuser . .
RUN mkdir -p /app/instance/uploads && chown -R appuser:appuser /app/instance
USER appuser
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/live', timeout=3)"
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "16", "--bind", "0.0.0.0:4000", "--timeout", "60", "run:app"]
