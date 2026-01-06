# Telegram LLM Bot

Telegram bot with access to LLM models (Claude, OpenAI, Google) and tools via agents.

## Working with the Project

### Start

```bash
# Start all containers
docker compose up -d

# Start with image rebuild
docker compose up -d --build

# Start specific service
docker compose up -d bot
docker compose up -d postgres
```

### Stop

```bash
# Stop all containers
docker compose down

# Stop with volume removal (CAUTION: deletes DB data)
docker compose down -v
```

### Restart

```bash
# Restart all containers
docker compose restart

# Restart specific service
docker compose restart bot

# Rebuild and restart bot
docker compose up -d --build bot
```

### Logs

```bash
# All logs
docker compose logs

# Real-time logs
docker compose logs -f

# Specific service logs
docker compose logs bot
docker compose logs postgres

# Last N lines
docker compose logs --tail=100 bot

# Logs with timestamps
docker compose logs -t bot
```

### Status

```bash
# List running containers
docker compose ps

# Resource usage
docker compose top
docker stats
```

### Debug

```bash
# Enter bot container
docker compose exec bot bash

# Enter PostgreSQL
docker compose exec postgres psql -U postgres

# Check environment variables
docker compose exec bot env
```

### Database

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U postgres -d postgres

# Database dump
docker compose exec postgres pg_dump -U postgres postgres > backup.sql

# Restore from dump
cat backup.sql | docker compose exec -T postgres psql -U postgres postgres
```

### Migrations (Alembic)

```bash
# Create migration
docker compose exec bot alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec bot alembic upgrade head

# Rollback last migration
docker compose exec bot alembic downgrade -1

# Show current version
docker compose exec bot alembic current
```

### Cleanup

```bash
# Remove stopped containers
docker compose rm

# Remove unused images
docker image prune

# Full Docker cleanup (CAUTION)
docker system prune -a
```

---

## Project Structure

See [CLAUDE.md](CLAUDE.md) for full architecture documentation.

```
├── bot/          # Telegram bot
├── postgres/     # PostgreSQL + migrations
├── grafana/      # Dashboards
├── loki/         # Logs
├── docs/         # Documentation
└── secrets/      # Tokens (not in git)
```

## Monitoring

| Service | URL | Purpose |
|---------|-----|---------|
| Grafana | http://localhost:3000 | Dashboards, metrics |
| CloudBeaver | http://localhost:8978 | SQL interface to DB |

## Secrets

Files in `secrets/` (empty templates in repo, fill with your values):
- `telegram_bot_token.txt` — Telegram Bot API token
- `anthropic_api_key.txt` — Claude API key
- `openai_api_key.txt` — OpenAI API key
- `google_api_key.txt` — Google API key
- `postgres_password.txt` — PostgreSQL password

After filling in secrets, run to prevent accidental commits:
```bash
git update-index --skip-worktree secrets/*
```
