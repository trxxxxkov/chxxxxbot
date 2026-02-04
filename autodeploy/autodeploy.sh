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

# Track the last deployed commit to detect local changes
# This is needed because commits made locally on the server won't be detected
# by comparing LOCAL vs REMOTE (they'll be equal after push)
LAST_DEPLOYED_COMMIT=$(git rev-parse HEAD)
log_info "Autodeploy started: checking $BRANCH every ${CHECK_INTERVAL}s"
log_info "Initial deployed commit: ${LAST_DEPLOYED_COMMIT:0:7}"

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
    log_info "Local: ${LOCAL:0:7}, Remote: ${REMOTE:0:7}, Deployed: ${LAST_DEPLOYED_COMMIT:0:7}"

    # Deploy needed if:
    # 1. Remote has new commits (REMOTE != LOCAL) - normal case
    # 2. Local has new commits since last deploy (LOCAL != LAST_DEPLOYED) - local commit case
    NEEDS_DEPLOY=false
    if [ "$LOCAL" != "$REMOTE" ]; then
        log_info "Remote has new commits ($LOCAL -> $REMOTE)"
        NEEDS_DEPLOY=true
    elif [ "$LOCAL" != "$LAST_DEPLOYED_COMMIT" ]; then
        log_info "Local has new commits since last deploy (${LAST_DEPLOYED_COMMIT:0:7} -> ${LOCAL:0:7})"
        NEEDS_DEPLOY=true
    fi

    if [ "$NEEDS_DEPLOY" = true ]; then
        log_info "Starting deployment..."

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

        # 4. Merge remote changes (preserves local commits)
        log_info "Updating code from GitHub..."
        if ! git merge --ff-only "origin/$BRANCH" 2>&1; then
            log_info "Fast-forward not possible, trying rebase..."
            if ! git rebase "origin/$BRANCH" 2>&1; then
                log_error "Rebase failed - local changes conflict with remote!"
                log_error "Manual intervention required. Aborting rebase..."
                git rebase --abort 2>/dev/null || true
                # Restart services without code update
                docker compose up -d
                continue
            fi
        fi

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

        # Update last deployed commit
        LAST_DEPLOYED_COMMIT=$(git rev-parse HEAD)
        log_info "Updated deployed commit: ${LAST_DEPLOYED_COMMIT:0:7}"
    fi

    # Cleanup any leftover backup
    rm -rf /tmp/secrets_backup 2>/dev/null || true
done
