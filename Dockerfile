FROM python:3.12-slim

WORKDIR /app

# Install git for repository cloning
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY README.md .
COPY server.py .

RUN pip install --no-cache-dir -e .

ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
