#!/bin/bash
# Auto-deploy: checks GitHub every minute, redeploys on new commits

set -e

REPO_DIR="/repo"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"
BRANCH="${BRANCH:-main}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-10}"

cd "$REPO_DIR"

log_info()  { echo "INFO $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_warn()  { echo "WARN $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_error() { echo "ERROR $(date '+%Y-%m-%d %H:%M:%S') $*"; }

log_info "Autodeploy started: checking $BRANCH every ${CHECK_INTERVAL}s"

while true; do
    sleep "$CHECK_INTERVAL"

    # Fetch latest
    git fetch origin "$BRANCH" --quiet 2>/dev/null || continue

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH")

    if [ "$LOCAL" != "$REMOTE" ]; then
        log_info "New commits detected ($LOCAL -> $REMOTE)"

        # 1. Graceful shutdown bot first (allows write-behind flush)
        log_info "Stopping bot gracefully..."
        docker compose stop -t "$GRACEFUL_TIMEOUT" bot 2>/dev/null || true

        # 2. Stop remaining services
        log_info "Stopping other services..."
        docker compose down

        # 3. Backup secrets before reset
        if [ -d "secrets" ]; then
            cp -r secrets /tmp/secrets_backup
        fi

        # 4. Hard reset to match GitHub exactly
        log_info "Updating code from GitHub..."
        git reset --hard "origin/$BRANCH"

        # 5. Restore secrets
        if [ -d "/tmp/secrets_backup" ]; then
            cp -r /tmp/secrets_backup/* secrets/ 2>/dev/null || true
            rm -rf /tmp/secrets_backup
        fi

        # 6. Rebuild and start all services
        log_info "Rebuilding and restarting..."
        docker compose build
        docker compose up -d

        # 7. Health check
        sleep 5
        if docker compose ps | grep -q "unhealthy\|Exit"; then
            log_warn "Some services unhealthy after deploy!"
            docker compose ps
        else
            log_info "Deploy completed successfully"
        fi
    fi

    # Cleanup any leftover backup
    rm -rf /tmp/secrets_backup 2>/dev/null || true
done
