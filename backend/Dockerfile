FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/start.sh

EXPOSE 8080

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/app/start.sh"]
