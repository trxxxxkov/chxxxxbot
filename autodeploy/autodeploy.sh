#!/bin/bash
# Auto-deploy: checks GitHub every 5 minutes, redeploys on new commits

set -e

REPO_DIR="/repo"
CHECK_INTERVAL="${CHECK_INTERVAL:-300}"
BRANCH="${BRANCH:-main}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-10}"

log_info()  { echo "INFO $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_warn()  { echo "WARN $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_error() { echo "ERROR $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Generate SSH config from available keys (files with matching .pub)
generate_ssh_config() {
    local ssh_dir="$HOME/.ssh"
    local config_file="/tmp/ssh_config"

    [ -d "$ssh_dir" ] || return 0

    {
        echo "Host github.com gitlab.com bitbucket.org"
        echo "    StrictHostKeyChecking accept-new"
        echo "    IdentitiesOnly yes"

        # Find all private keys (files that have a corresponding .pub file)
        for pub in "$ssh_dir"/*.pub; do
            [ -f "$pub" ] || continue
            key="${pub%.pub}"
            [ -f "$key" ] && echo "    IdentityFile $key"
        done
    } > "$config_file"

    # Use our generated config
    export GIT_SSH_COMMAND="ssh -F $config_file"

    key_count=$(grep -c "IdentityFile" "$config_file" 2>/dev/null || echo 0)
    log_info "SSH config generated with $key_count key(s)"
}

generate_ssh_config

cd "$REPO_DIR"

log_info "Autodeploy started: checking $BRANCH every ${CHECK_INTERVAL}s"

while true; do
    sleep "$CHECK_INTERVAL"

    # Fetch latest
    log_info "Checking for updates..."
    if ! git fetch origin "$BRANCH" --quiet 2>&1; then
        log_error "git fetch failed"
        continue
    fi

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH")
    log_info "Local: ${LOCAL:0:7}, Remote: ${REMOTE:0:7}"

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
