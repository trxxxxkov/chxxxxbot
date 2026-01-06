# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better caching
COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir \
    aiogram==3.15.0 \
    structlog>=24.1.0 \
    pydantic>=2.0.0

# Copy application code
COPY . .

# Run bot
CMD ["python", "main.py"]
