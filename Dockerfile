FROM python:3.12-slim

WORKDIR /app

# Install git for repository cloning
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY README.md .

RUN pip install --no-cache-dir -e .

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn code_compass.web.app:app --host 0.0.0.0 --port ${PORT}"]
