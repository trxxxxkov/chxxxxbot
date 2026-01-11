# Phase 3 — Infrastructure (Monitoring & Admin)

## Overview

Добавление инфраструктуры мониторинга и администрирования:
- **Grafana** — единый веб-интерфейс для логов и метрик
- **Loki** — хранилище логов
- **Promtail** — сборщик логов из Docker контейнеров
- **Prometheus** — хранилище метрик
- **CloudBeaver** — веб-интерфейс для PostgreSQL

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  External Access (88.218.68.98)              │
├─────────────────────────────────────────────────────────────┤
│  :3000 → Grafana        (login/password from secrets)       │
│  :8978 → CloudBeaver    (built-in auth)                     │
├─────────────────────────────────────────────────────────────┤
│                    Internal Network Only                     │
├─────────────────────────────────────────────────────────────┤
│  Loki (:3100)       ← logs      ← Promtail                  │
│  Prometheus (:9090) ← metrics   ← Bot /metrics endpoint     │
│  PostgreSQL (:5432) ← data      ← Bot application           │
└─────────────────────────────────────────────────────────────┘
```

## Repository Structure

```
chxxxxbot/
├── bot/                    # Telegram bot (existing)
├── postgres/               # PostgreSQL + Alembic (existing)
├── grafana/                # Stage 2
│   ├── grafana.ini
│   └── provisioning/
│       ├── datasources/
│       │   └── datasources.yaml
│       └── dashboards/
│           ├── dashboards.yaml
│           └── bot-overview.json
├── loki/                   # Stage 1
│   └── loki-config.yaml
├── promtail/               # Stage 1
│   └── promtail-config.yaml
├── prometheus/             # Stage 3
│   └── prometheus.yml
├── cloudbeaver/            # Stage 4
│   └── (auto-generated config)
├── secrets/
│   ├── grafana_password.txt  # ✅ Created
│   └── ... (existing secrets)
└── compose.yaml
```

---

## Stage 1: Loki + Promtail (Centralized Logging)

### Components

| Component | Version | Purpose |
|-----------|---------|---------|
| Loki | 3.0.x | Log aggregation and storage |
| Promtail | 3.0.x | Log collection agent |

### How It Works

1. **Docker containers** write logs to stdout/stderr
2. **Promtail** reads logs from Docker via `/var/lib/docker/containers`
3. **Promtail** adds labels (container_name, compose_service, etc.)
4. **Promtail** pushes logs to **Loki**
5. **Grafana** queries Loki via LogQL

### Configuration Files

#### loki/loki-config.yaml

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 100

schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093

limits_config:
  retention_period: 720h  # 30 days
```

#### promtail/promtail-config.yaml

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Keep only containers from our compose project
      - source_labels: ['__meta_docker_container_label_com_docker_compose_project']
        regex: chxxxxbot
        action: keep
      # Use container name as label
      - source_labels: ['__meta_docker_container_name']
        regex: '/(.+)'
        target_label: container
      # Use compose service name
      - source_labels: ['__meta_docker_container_label_com_docker_compose_service']
        target_label: service
    pipeline_stages:
      # Try to parse JSON logs (structlog format)
      - json:
          expressions:
            level: level
            event: event
            logger: logger
            user_id: user_id
            chat_id: chat_id
            handler: handler
      # Set log level from parsed JSON
      - labels:
          level:
          logger:
          handler:
```

### Docker Compose Services

```yaml
loki:
  image: grafana/loki:3.0.0
  restart: unless-stopped
  volumes:
    - ./loki/loki-config.yaml:/etc/loki/local-config.yaml:ro
    - loki_data:/loki
  command: -config.file=/etc/loki/local-config.yaml
  networks:
    - botnet
  # No ports exposed - internal only

promtail:
  image: grafana/promtail:3.0.0
  restart: unless-stopped
  volumes:
    - ./promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro
    - /var/lib/docker/containers:/var/lib/docker/containers:ro
    - /var/run/docker.sock:/var/run/docker.sock
  command: -config.file=/etc/promtail/config.yaml
  depends_on:
    - loki
  networks:
    - botnet
  # No ports exposed - internal only
```

### Verification

```bash
# Check Loki is running
docker compose logs loki

# Check Promtail is collecting logs
docker compose logs promtail

# Test Loki API (from host)
docker compose exec loki wget -qO- http://localhost:3100/ready

# Query logs via API
docker compose exec loki wget -qO- 'http://localhost:3100/loki/api/v1/labels'
```

---

## Stage 2: Grafana (Web Interface)

### Components

| Component | Version | Purpose |
|-----------|---------|---------|
| Grafana | 11.x | Dashboards, exploration, alerts |

### Configuration Files

#### grafana/grafana.ini

```ini
[server]
http_port = 3000
domain = 88.218.68.98

[security]
admin_user = admin
admin_password = $__file{/run/secrets/grafana_password}

[auth.anonymous]
enabled = false

[users]
allow_sign_up = false
```

#### grafana/provisioning/datasources/datasources.yaml

```yaml
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: false

  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    editable: false
```

### Docker Compose Service

```yaml
grafana:
  image: grafana/grafana:11.4.0
  restart: unless-stopped
  secrets:
    - grafana_password
  environment:
    - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_password
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning:ro
    - grafana_data:/var/lib/grafana
  ports:
    - "3000:3000"  # External access
  depends_on:
    - loki
  networks:
    - botnet
```

### Access

- URL: `http://88.218.68.98:3000`
- Username: `admin`
- Password: from `secrets/grafana_password.txt`

### Useful LogQL Queries

```logql
# All bot logs
{service="bot"}

# Only errors
{service="bot"} | json | level="error"

# Specific user
{service="bot"} | json | user_id="123456789"

# Claude API calls
{service="bot"} | json | logger="claude"

# Errors with stack trace
{service="bot"} | json | level="error" | line_format "{{.event}}: {{.error}}"

# Count messages per minute
count_over_time({service="bot"} | json | event="message_received" [1m])

# Response time histogram
{service="bot"} | json | event="response_sent" | unwrap duration | histogram_over_time(1m)
```

---

## Stage 3: Prometheus (Metrics)

### Components

| Component | Version | Purpose |
|-----------|---------|---------|
| Prometheus | 2.x | Metrics collection and storage |
| prometheus-client | Python | Expose /metrics endpoint |

### Bot Metrics Endpoint

Add to bot:

```python
# bot/utils/metrics.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest

MESSAGES_TOTAL = Counter(
    'bot_messages_total',
    'Total messages received',
    ['chat_type', 'handler']
)

TOKENS_TOTAL = Counter(
    'bot_tokens_total',
    'Total Claude tokens used',
    ['type', 'model']  # type: input/output/cache
)

RESPONSE_TIME = Histogram(
    'bot_response_seconds',
    'Response time in seconds',
    ['handler'],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

ACTIVE_USERS = Gauge(
    'bot_active_users',
    'Number of active users in last hour'
)

BALANCE_TOTAL = Gauge(
    'bot_balance_total_usd',
    'Total user balance in USD'
)
```

### Configuration

#### prometheus/prometheus.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'bot'
    static_configs:
      - targets: ['bot:8080']
    metrics_path: /metrics
```

### Docker Compose Service

```yaml
prometheus:
  image: prom/prometheus:v2.54.0
  restart: unless-stopped
  volumes:
    - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    - prometheus_data:/prometheus
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'
    - '--storage.tsdb.retention.time=30d'
  networks:
    - botnet
  # No ports exposed - internal only, access via Grafana
```

---

## Stage 4: CloudBeaver (DB Admin)

### Components

| Component | Version | Purpose |
|-----------|---------|---------|
| CloudBeaver | latest | Web-based database admin |

### Docker Compose Service

```yaml
cloudbeaver:
  image: dbeaver/cloudbeaver:latest
  restart: unless-stopped
  volumes:
    - cloudbeaver_data:/opt/cloudbeaver/workspace
  ports:
    - "8978:8978"  # External access
  depends_on:
    postgres:
      condition: service_healthy
  networks:
    - botnet
```

### First-Time Setup

1. Open `http://88.218.68.98:8978`
2. Create admin account (first user becomes admin)
3. Add PostgreSQL connection:
   - Host: `postgres`
   - Port: `5432`
   - Database: `postgres`
   - User: `postgres`
   - Password: from `secrets/postgres_password.txt`

### Access

- URL: `http://88.218.68.98:8978`
- Auth: Created during first-time setup

---

## Complete compose.yaml

After all stages:

```yaml
services:
  # === Application ===
  postgres:
    image: postgres:16
    restart: unless-stopped
    secrets:
      - postgres_password
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_DB=postgres
      - POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - botnet
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  bot:
    build: ./bot
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    secrets:
      - telegram_bot_token
      - postgres_password
      - anthropic_api_key
      - e2b_api_key
      - openai_api_key
      - google_api_key
      - privileged_users
    volumes:
      - ./bot:/app
      - ./postgres:/postgres
    environment:
      - PYTHONUNBUFFERED=1
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_USER=postgres
      - DATABASE_NAME=postgres
    networks:
      - botnet

  # === Logging ===
  loki:
    image: grafana/loki:3.0.0
    restart: unless-stopped
    volumes:
      - ./loki/loki-config.yaml:/etc/loki/local-config.yaml:ro
      - loki_data:/loki
    command: -config.file=/etc/loki/local-config.yaml
    networks:
      - botnet

  promtail:
    image: grafana/promtail:3.0.0
    restart: unless-stopped
    volumes:
      - ./promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock
    command: -config.file=/etc/promtail/config.yaml
    depends_on:
      - loki
    networks:
      - botnet

  # === Metrics ===
  prometheus:
    image: prom/prometheus:v2.54.0
    restart: unless-stopped
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
    networks:
      - botnet

  # === Web Interfaces ===
  grafana:
    image: grafana/grafana:11.4.0
    restart: unless-stopped
    secrets:
      - grafana_password
    environment:
      - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_password
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - loki
      - prometheus
    networks:
      - botnet

  cloudbeaver:
    image: dbeaver/cloudbeaver:latest
    restart: unless-stopped
    volumes:
      - cloudbeaver_data:/opt/cloudbeaver/workspace
    ports:
      - "8978:8978"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - botnet

networks:
  botnet:
    driver: bridge

volumes:
  postgres_data:
  loki_data:
  prometheus_data:
  grafana_data:
  cloudbeaver_data:

secrets:
  telegram_bot_token:
    file: ./secrets/telegram_bot_token.txt
  postgres_password:
    file: ./secrets/postgres_password.txt
  anthropic_api_key:
    file: ./secrets/anthropic_api_key.txt
  e2b_api_key:
    file: ./secrets/e2b_api_key.txt
  openai_api_key:
    file: ./secrets/openai_api_key.txt
  google_api_key:
    file: ./secrets/google_api_key.txt
  privileged_users:
    file: ./secrets/privileged_users.txt
  grafana_password:
    file: ./secrets/grafana_password.txt
```

---

## Implementation Order

| Stage | Components | Status |
|-------|------------|--------|
| 1 | Loki + Promtail | 🔄 In Progress |
| 2 | Grafana | ⏳ Pending |
| 3 | Prometheus | ⏳ Pending |
| 4 | CloudBeaver | ⏳ Pending |

---

## Verification Checklist

### Stage 1: Loki + Promtail
- [ ] Loki container running
- [ ] Promtail container running
- [ ] Logs being collected
- [ ] `docker compose logs loki` shows no errors

### Stage 2: Grafana
- [ ] Grafana accessible at :3000
- [ ] Login with admin/password works
- [ ] Loki datasource connected
- [ ] Can query logs via Explore

### Stage 3: Prometheus
- [ ] Prometheus container running
- [ ] Bot /metrics endpoint working
- [ ] Prometheus scraping bot metrics
- [ ] Grafana can query Prometheus

### Stage 4: CloudBeaver
- [ ] CloudBeaver accessible at :8978
- [ ] Admin account created
- [ ] PostgreSQL connection configured
- [ ] Can browse tables and run queries
