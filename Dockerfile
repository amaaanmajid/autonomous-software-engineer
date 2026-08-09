FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first (keeps image ~1.5 GB smaller than default)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

RUN mkdir -p workspace data app/static

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 600"]
