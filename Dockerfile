FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY prompts ./prompts
COPY data/sources.json ./data/sources.json
COPY data/parsed ./data/parsed
COPY data/eval ./data/eval
COPY data/index.db ./data/index.db

RUN pip install --no-cache-dir . \
    && addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app
EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
