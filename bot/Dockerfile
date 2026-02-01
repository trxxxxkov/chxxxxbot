# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for asyncpg, PostgreSQL client, libmagic,
# LaTeX (full rendering with TikZ support), and PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    postgresql-client \
    libmagic1 \
    file \
    # LaTeX for render_latex tool (TikZ, complex math, diagrams)
    texlive-latex-base \
    texlive-latex-extra \
    texlive-pictures \
    texlive-fonts-recommended \
    # Cyrillic support for LaTeX
    texlive-lang-cyrillic \
    # PDF to image conversion
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir \
    aiogram>=3.24.0 \
    structlog>=24.1.0 \
    pydantic>=2.0.0 \
    sqlalchemy[asyncio]>=2.0.0 \
    asyncpg>=0.29.0 \
    alembic>=1.13.0 \
    anthropic>=0.40.0 \
    openai>=1.0.0 \
    e2b-code-interpreter>=1.0.0 \
    google-genai>=1.0.0 \
    pillow>=10.0.0 \
    matplotlib>=3.8.0 \
    pytest>=7.4.0 \
    pytest-asyncio>=0.21.0 \
    pytest-cov>=4.1.0 \
    aiosqlite>=0.19.0 \
    prometheus-client>=0.20.0 \
    aiohttp>=3.9.0 \
    python-magic>=0.4.27 \
    "redis[hiredis]>=5.0.0" \
    pdf2image>=1.17.0 \
    openpyxl>=3.1.0

# Copy application code
COPY . .

# Expose metrics port
EXPOSE 8080

# Run migrations and start bot
CMD ["sh", "-c", "cd /postgres && alembic upgrade head && cd /app && python main.py"]
