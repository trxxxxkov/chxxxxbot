# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for asyncpg and PostgreSQL client
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir \
    aiogram==3.15.0 \
    structlog>=24.1.0 \
    pydantic>=2.0.0 \
    sqlalchemy[asyncio]>=2.0.0 \
    asyncpg>=0.29.0 \
    alembic>=1.13.0

# Copy application code and Alembic config
COPY . .
COPY ../postgres /postgres

# Run migrations and start bot
CMD ["sh", "-c", "cd /postgres && alembic upgrade head && cd /app && python main.py"]
