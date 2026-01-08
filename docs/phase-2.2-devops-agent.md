# Phase 2.2: DevOps Agent (Self-Healing Bot)

**Status:** 📋 Planned

**Purpose:** Self-healing bot with autonomous code fixing, feature development, and deployment via Agent SDK integration.

**Reference:** Based on [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Use Cases](#use-cases)
- [Components](#components)
- [Security](#security)
- [Implementation Tasks](#implementation-tasks)
- [Cost Estimation](#cost-estimation)
- [Related Documents](#related-documents)

---

## Overview

Phase 2.2 adds a **DevOps Agent** - an autonomous AI agent that can:
- 🔧 **Auto-fix errors** detected in production logs
- 🚀 **Implement new features** on owner's request via Telegram
- 📊 **Review code** and suggest improvements
- 🔄 **Create PRs** with fixes/features
- ⚙️ **Deploy changes** after owner approval
- 🤖 **Self-healing** bot that maintains itself

**Core Idea:**
Bot owner can chat with their bot in Telegram, and commands like `/agent add new feature` are delegated to an Agent SDK-powered service that reads code, makes changes, creates PRs, and deploys after approval.

### Prerequisites

- ✅ Phase 1.5: Tools architecture
- ✅ Phase 2.1: Payment system
- ✅ Monitoring (Grafana + Loki for error detection)
- ✅ GitHub repository for bot code
- ✅ Docker Compose infrastructure

### Key Benefits

- **Self-healing:** Automatic bug fixes when errors occur
- **Faster development:** Owner requests features via Telegram, agent implements
- **Code quality:** Automatic reviews and suggestions
- **Zero downtime:** Agent handles deployments
- **Audit trail:** All changes via Git PRs

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Compose Stack                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │ Telegram Bot │◄────────┤  PostgreSQL  │                 │
│  │  (Phase 1-2) │         │   Database   │                 │
│  └──────┬───────┘         └──────────────┘                 │
│         │                                                    │
│         │ POST /agent/command                               │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │          Agent Service Container              │          │
│  │  ┌────────────────────────────────────────┐ │          │
│  │  │      Claude Agent SDK Runtime          │ │          │
│  │  │  ┌──────────────────────────────────┐ │ │          │
│  │  │  │  Built-in Tools:                 │ │ │          │
│  │  │  │  - Read (read code files)        │ │ │          │
│  │  │  │  - Write (create new files)      │ │ │          │
│  │  │  │  - Edit (modify existing code)   │ │ │          │
│  │  │  │  - Bash (git, docker commands)   │ │ │          │
│  │  │  │  - Glob (find files)             │ │ │          │
│  │  │  │  - Grep (search code)            │ │ │          │
│  │  │  └──────────────────────────────────┘ │ │          │
│  │  └────────────────────────────────────────┘ │          │
│  │                                               │          │
│  │  FastAPI Server:                             │          │
│  │  - POST /agent/command (from Telegram)       │          │
│  │  - POST /agent/auto-fix (from Loki alerts)   │          │
│  │  - POST /agent/approve-pr (merge + deploy)   │          │
│  └───────────────┬──────────────────────────────┘          │
│                  │                                           │
│                  │ Shared Volume: /workspace (bot code)     │
│                  │ Docker Socket: /var/run/docker.sock      │
│                  │                                           │
└──────────────────┼───────────────────────────────────────────┘
                   │
                   │ GitHub API
                   ▼
            ┌──────────────┐
            │    GitHub     │
            │  - Create PR  │
            │  - Merge PR   │
            │  - Comments   │
            └──────────────┘
                   │
                   │ Webhook: PR merged
                   ▼
            ┌──────────────┐
            │     Loki      │
            │ Error alerts  │
            │  → webhook    │
            └──────────────┘
```

### Data Flow

**1. Owner requests feature:**
```
Owner in Telegram: /agent add /stats command
    ↓
Telegram bot → POST http://agent:8001/agent/command
    ↓
Agent SDK: query("Add /stats command...")
    ↓
Agent: Read(handlers/), Glob(*.py), Grep(Command)
Agent: Edit(handlers/stats.py), Edit(repositories/stats.py)
Agent: Bash("git checkout -b feature/stats")
Agent: Bash("git commit -m 'Add /stats command'")
    ↓
Agent: GitHub API → Create PR #126
    ↓
Agent → Telegram: "✅ Feature implemented. PR: https://..."
    ↓
Owner: /approve_pr 126
    ↓
Agent: GitHub API → Merge PR
Agent: Bash("docker compose restart bot")
    ↓
Agent → Telegram: "✅ Bot restarted with new feature"
```

**2. Automatic error fixing:**
```
Error in logs: Traceback in bot/core/claude/context.py
    ↓
Loki alert → POST http://agent:8001/agent/auto-fix
    ↓
Agent SDK: query("Fix error: {traceback}")
    ↓
Agent: Read(context.py), identifies bug
Agent: Edit(context.py), adds error handling
Agent: Bash("git checkout -b fix/token-limit-error")
Agent: Bash("git commit -m 'Fix: token limit error'")
    ↓
Agent: GitHub API → Create PR #127
    ↓
Agent → Telegram: "🔧 Auto-fix: {summary}. PR: https://..."
    ↓
Owner: /approve_pr 127
    ↓
Agent: Merge + restart bot
```

---

## Use Cases

### 1. Self-Healing on Production Errors

**Scenario:** Error detected in production logs

**Flow:**
1. Loki detects error pattern in logs
2. Loki webhook → Agent Service
3. Agent reads error traceback
4. Agent locates bug in code (Grep, Read)
5. Agent fixes bug (Edit)
6. Agent creates fix branch + commits
7. Agent creates PR with explanation
8. Agent notifies owner in Telegram
9. Owner reviews PR, approves via `/approve_pr`
10. Agent merges PR + restarts bot
11. Error resolved ✅

**Example:**
```
🔧 Auto-Fix Alert

Error: KeyError in bot/telegram/handlers/claude.py:156
Line: user_data['thread_id']

Fix Applied:
+ Added null check: if 'thread_id' not in user_data
+ Return early with error message

PR #127: https://github.com/user/chxxxxbot/pull/127
Branch: fix/keyerror-thread-id

Review and approve: /approve_pr 127
```

### 2. Feature Development on Demand

**Scenario:** Owner wants new feature

**Flow:**
1. Owner: `/agent add command /balance that shows user's current balance`
2. Telegram bot → Agent Service
3. Agent analyzes codebase structure (reads CLAUDE.md, docs/)
4. Agent identifies pattern: handlers, repositories, etc.
5. Agent implements:
   - Handler: `bot/telegram/handlers/balance.py`
   - Repository method: `UserRepository.get_balance()`
   - Router registration
   - Tests
6. Agent creates feature branch + commits
7. Agent creates PR with code preview
8. Agent notifies owner with summary
9. Owner reviews code, approves
10. Agent merges + deploys

**Example:**
```
✅ Feature Implemented: /balance command

Created files:
- bot/telegram/handlers/balance.py (45 lines)
- tests/telegram/handlers/test_balance.py (23 lines)

Modified files:
- bot/telegram/handlers/__init__.py (added import)

Preview:
```python
@router.message(Command("balance"))
async def balance_command(message: Message, user: User):
    await message.answer(
        f"💰 Your balance: ${user.balance:.2f}"
    )
```

PR #128: https://github.com/user/chxxxxbot/pull/128

Approve: /approve_pr 128
```

### 3. Code Review on Request

**Scenario:** Owner wants review of recent changes

**Flow:**
1. Owner: `/agent review last commit`
2. Agent reads recent commits (Bash: git log)
3. Agent analyzes changed files (Read)
4. Agent identifies:
   - Potential bugs
   - Performance issues
   - Security concerns
   - Best practice violations
5. Agent creates suggestions
6. Agent optionally creates PR with improvements

**Example:**
```
📊 Code Review: Commit abc123

Files reviewed: 3
✅ bot/telegram/handlers/start.py - Good
⚠️  bot/core/claude/context.py - Issues found
✅ bot/db/repositories/user.py - Good

Issues:
1. Missing error handling (line 45)
   - TokenLimitExceeded not caught
   - Could crash on large contexts

2. Potential memory leak (line 78)
   - Messages list grows unbounded
   - Consider implementing sliding window

3. SQL injection risk (line 123)
   - Raw string interpolation in query
   - Use parameterized queries

Suggestions PR #129: https://github.com/.../pull/129
```

### 4. Refactoring and Optimization

**Scenario:** Owner wants code improvements

**Flow:**
1. Owner: `/agent refactor claude handler to improve readability`
2. Agent analyzes handler code
3. Agent applies refactoring:
   - Extract methods
   - Simplify complex logic
   - Add type hints
   - Improve naming
4. Agent creates PR with before/after
5. Owner reviews, approves

---

## Components

### 1. Agent Service Container

**Technology:**
- Python 3.12+ or Node.js 18+
- Claude Agent SDK (Python or TypeScript)
- FastAPI (Python) or Express (Node.js)
- Claude Code CLI runtime

**File Structure:**
```
agent-service/
├── Dockerfile
├── main.py (or index.ts)
├── agent/
│   ├── __init__.py
│   ├── command_handler.py    # Handle Telegram commands
│   ├── auto_fix.py            # Auto-fix logic
│   ├── github_client.py       # GitHub API integration
│   ├── docker_control.py      # Docker operations
│   └── security.py            # Access control, protected paths
├── config.py
├── requirements.txt (or package.json)
└── tests/
```

**Dockerfile:**
```dockerfile
FROM node:20-slim  # or python:3.12-slim

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

# Install Agent SDK
RUN npm install -g @anthropic-ai/claude-agent-sdk
# or: pip install claude-agent-sdk

# Install dependencies
COPY package.json ./
RUN npm install
# or: COPY requirements.txt && pip install -r requirements.txt

# Copy application
COPY . .

EXPOSE 8001

CMD ["npm", "start"]
# or: CMD ["python", "main.py"]
```

**compose.yaml addition:**
```yaml
services:
  agent:
    build: ./agent-service
    container_name: agent
    volumes:
      - ./:/workspace:rw  # Full access to bot code
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Docker control
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - OWNER_TELEGRAM_ID=${OWNER_TELEGRAM_ID}
      - ALLOWED_TOOLS=Read,Write,Edit,Bash,Glob,Grep
    ports:
      - "8001:8001"
    networks:
      - chxxxxbot-network
    restart: unless-stopped
```

### 2. Agent Command Handler

```python
# agent-service/main.py

from fastapi import FastAPI, HTTPException, BackgroundTasks
from claude_agent_sdk import query, ClaudeAgentOptions
from pydantic import BaseModel
import os

app = FastAPI()

OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WORKSPACE = "/workspace"

class AgentCommandRequest(BaseModel):
    prompt: str
    user_id: int
    message_id: int

class ApprovalRequest(BaseModel):
    pr_number: int
    user_id: int

@app.post("/agent/command")
async def handle_command(
    request: AgentCommandRequest,
    background_tasks: BackgroundTasks
):
    """Handle agent command from Telegram bot owner"""

    # Security: Only bot owner can use agent
    if request.user_id != OWNER_ID:
        raise HTTPException(403, "Only bot owner can use agent")

    # Log command
    logger.info(
        "agent_command_received",
        user_id=request.user_id,
        prompt=request.prompt
    )

    # Run agent in background
    background_tasks.add_task(
        run_agent_task,
        prompt=request.prompt,
        user_id=request.user_id
    )

    return {"status": "started", "message": "Agent is working..."}

async def run_agent_task(prompt: str, user_id: int):
    """Execute agent task with full code access"""

    try:
        # Stream updates to Telegram
        await send_telegram_message(
            user_id,
            "🤖 Agent started working..."
        )

        # Run Agent SDK with code access
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                working_directory=WORKSPACE,
                permission_mode="acceptEdits",  # Auto-accept file edits
                hooks={
                    "PreToolUse": [security_check_hook],
                    "PostToolUse": [audit_log_hook]
                }
            )
        ):
            # Stream thinking to user
            if hasattr(message, "thinking"):
                await send_telegram_message(
                    user_id,
                    f"💭 {message.thinking}"
                )

            # Final result
            if hasattr(message, "result"):
                result = message.result

                # Check if PR was created
                if "PR #" in result or "pull/" in result:
                    pr_number = extract_pr_number(result)
                    pr_url = extract_pr_url(result)

                    await send_telegram_message(
                        user_id,
                        f"✅ {result}\n\n"
                        f"🔗 PR: {pr_url}\n\n"
                        f"Review code and approve:\n"
                        f"/approve_pr {pr_number}"
                    )
                else:
                    await send_telegram_message(user_id, f"✅ {result}")

        logger.info(
            "agent_task_completed",
            user_id=user_id,
            prompt=prompt
        )

    except Exception as e:
        logger.error(
            "agent_task_failed",
            user_id=user_id,
            error=str(e),
            exc_info=True
        )

        await send_telegram_message(
            user_id,
            f"❌ Agent error: {str(e)}"
        )

@app.post("/agent/approve-pr")
async def approve_pr(request: ApprovalRequest):
    """Merge PR and deploy changes"""

    # Security check
    if request.user_id != OWNER_ID:
        raise HTTPException(403, "Only bot owner can approve PRs")

    try:
        # Merge PR via GitHub API
        pr_info = await github_client.merge_pr(request.pr_number)

        await send_telegram_message(
            request.user_id,
            f"✅ PR #{request.pr_number} merged: {pr_info['title']}\n"
            f"Restarting bot..."
        )

        # Restart bot container
        await restart_bot()

        await send_telegram_message(
            request.user_id,
            f"✅ Bot restarted successfully!\n"
            f"Changes are now live."
        )

        return {"status": "deployed"}

    except Exception as e:
        logger.error(
            "pr_approval_failed",
            pr_number=request.pr_number,
            error=str(e)
        )
        raise HTTPException(500, f"Failed to merge PR: {str(e)}")
```

### 3. Auto-Fix Handler

```python
# agent-service/agent/auto_fix.py

from pydantic import BaseModel

class ErrorReport(BaseModel):
    error_id: str
    summary: str
    traceback: str
    file_path: str
    line_number: int
    timestamp: str

@app.post("/agent/auto-fix")
async def auto_fix_error(error: ErrorReport):
    """Handle automatic error fixing from Loki alerts"""

    logger.info(
        "auto_fix_triggered",
        error_id=error.error_id,
        file_path=error.file_path
    )

    # Construct detailed prompt for agent
    prompt = f"""
Production Error Detected - Auto-Fix Required

Error Summary: {error.summary}
File: {error.file_path}:{error.line_number}
Timestamp: {error.timestamp}

Full Traceback:
{error.traceback}

Please:
1. Read the file {error.file_path} and locate the error
2. Analyze the root cause
3. Implement a fix that addresses the issue
4. Add appropriate error handling to prevent recurrence
5. Create a git branch named 'fix/{error.error_id}'
6. Commit with message: 'Fix: {error.summary}'
7. Create a GitHub PR with:
   - Clear description of the bug
   - Explanation of the fix
   - Any additional changes made
8. Report the PR URL and summary

Follow best practices from CLAUDE.md and existing codebase patterns.
"""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep"],
                working_directory=WORKSPACE,
                permission_mode="acceptEdits"
            )
        ):
            if hasattr(message, "result"):
                result = message.result

                # Extract PR info
                pr_url = extract_pr_url(result)
                pr_number = extract_pr_number(result)

                # Notify owner
                await send_telegram_message(
                    OWNER_ID,
                    f"🔧 Auto-Fix Completed\n\n"
                    f"Error: {error.summary}\n"
                    f"File: {error.file_path}:{error.line_number}\n\n"
                    f"Fix created and PR opened:\n"
                    f"{pr_url}\n\n"
                    f"Agent's explanation:\n{result}\n\n"
                    f"Review and approve: /approve_pr {pr_number}"
                )

        return {"status": "fix_created", "pr_url": pr_url}

    except Exception as e:
        logger.error(
            "auto_fix_failed",
            error_id=error.error_id,
            error=str(e)
        )

        # Notify owner of failure
        await send_telegram_message(
            OWNER_ID,
            f"❌ Auto-Fix Failed\n\n"
            f"Error: {error.summary}\n"
            f"Agent error: {str(e)}\n\n"
            f"Manual intervention required."
        )

        raise
```

### 4. GitHub Integration

```python
# agent-service/agent/github_client.py

import requests
import os

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("GITHUB_REPO_OWNER")
REPO_NAME = os.getenv("GITHUB_REPO_NAME")

BASE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

class GitHubClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

    async def create_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main"
    ):
        """Create a pull request"""

        url = f"{BASE_URL}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        }

        response = requests.post(url, json=data, headers=self.headers)
        response.raise_for_status()

        pr_data = response.json()

        logger.info(
            "github_pr_created",
            pr_number=pr_data["number"],
            pr_url=pr_data["html_url"]
        )

        return pr_data

    async def merge_pr(self, pr_number: int, merge_method: str = "squash"):
        """Merge a pull request"""

        url = f"{BASE_URL}/pulls/{pr_number}/merge"
        data = {
            "merge_method": merge_method
        }

        response = requests.put(url, json=data, headers=self.headers)
        response.raise_for_status()

        logger.info(
            "github_pr_merged",
            pr_number=pr_number
        )

        return response.json()

    async def get_pr(self, pr_number: int):
        """Get PR details"""

        url = f"{BASE_URL}/pulls/{pr_number}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        return response.json()

    async def add_pr_comment(self, pr_number: int, comment: str):
        """Add a comment to PR"""

        url = f"{BASE_URL}/issues/{pr_number}/comments"
        data = {"body": comment}

        response = requests.post(url, json=data, headers=self.headers)
        response.raise_for_status()

        return response.json()

github_client = GitHubClient()
```

### 5. Docker Control

```python
# agent-service/agent/docker_control.py

import docker
import asyncio

client = docker.from_env()

async def restart_bot():
    """Restart bot container"""

    try:
        # Get bot container
        container = client.containers.get("bot")

        logger.info("restarting_bot_container")

        # Restart
        container.restart(timeout=10)

        # Wait for container to be healthy
        await wait_for_healthy(container)

        logger.info("bot_container_restarted")

    except docker.errors.NotFound:
        logger.error("bot_container_not_found")
        raise Exception("Bot container not found")
    except Exception as e:
        logger.error("bot_restart_failed", error=str(e))
        raise

async def wait_for_healthy(container, timeout: int = 30):
    """Wait for container to become healthy"""

    for _ in range(timeout):
        container.reload()

        if container.status == "running":
            # Check if container is actually responding
            # Could add health check endpoint ping here
            return True

        await asyncio.sleep(1)

    raise Exception("Container did not become healthy in time")

async def get_logs(container_name: str, lines: int = 100):
    """Get recent container logs"""

    try:
        container = client.containers.get(container_name)
        logs = container.logs(tail=lines).decode('utf-8')
        return logs
    except Exception as e:
        logger.error("failed_to_get_logs", error=str(e))
        return None
```

### 6. Security Module

```python
# agent-service/agent/security.py

from pathlib import Path

# Protected paths that agent cannot modify
PROTECTED_PATHS = [
    "secrets/",
    ".env",
    "*.key",
    "*.pem",
    "compose.yaml",           # Prevent self-modification
    "docker-compose.yaml",
    "agent-service/",         # Prevent agent from modifying itself
    ".git/config",            # Protect git config
]

# Owner-only operations
RESTRICTED_OPERATIONS = [
    "docker",
    "compose",
    "rm -rf",
    "shutdown",
    "reboot"
]

async def security_check_hook(input_data, tool_use_id, context):
    """Pre-tool-use security validation"""

    tool_name = input_data.get('tool_name')
    tool_input = input_data.get('tool_input', {})

    # File path validation
    if tool_name in ["Read", "Write", "Edit"]:
        file_path = tool_input.get('file_path', '')

        # Check against protected paths
        for pattern in PROTECTED_PATHS:
            if pattern in file_path or Path(file_path).match(pattern):
                logger.warning(
                    "security_blocked_file_access",
                    file_path=file_path,
                    pattern=pattern
                )
                raise Exception(
                    f"Access denied: {file_path} is protected"
                )

    # Bash command validation
    if tool_name == "Bash":
        command = tool_input.get('command', '')

        # Check for dangerous commands
        for restricted in RESTRICTED_OPERATIONS:
            if restricted in command.lower():
                logger.warning(
                    "security_blocked_command",
                    command=command,
                    restriction=restricted
                )
                raise Exception(
                    f"Command blocked: '{restricted}' not allowed"
                )

    return {}

async def audit_log_hook(input_data, tool_use_id, context):
    """Post-tool-use audit logging"""

    tool_name = input_data.get('tool_name')
    tool_input = input_data.get('tool_input', {})

    # Log all file modifications
    if tool_name in ["Write", "Edit"]:
        file_path = tool_input.get('file_path')

        logger.info(
            "agent_file_modified",
            tool_name=tool_name,
            file_path=file_path,
            tool_use_id=tool_use_id
        )

    # Log all bash commands
    if tool_name == "Bash":
        command = tool_input.get('command')

        logger.info(
            "agent_bash_executed",
            command=command,
            tool_use_id=tool_use_id
        )

    return {}

def validate_user_is_owner(user_id: int) -> bool:
    """Validate that user is bot owner"""
    return user_id == OWNER_ID
```

### 7. Telegram Integration

```python
# bot/telegram/handlers/agent.py

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
import httpx

router = Router()

AGENT_SERVICE_URL = "http://agent:8001"
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))

@router.message(Command("agent"))
async def agent_command(message: Message):
    """Send command to DevOps Agent"""

    # Security: only owner
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ This command is only available to bot owner")
        return

    # Extract command text
    command_text = message.text.replace("/agent ", "").strip()

    if not command_text:
        await message.answer(
            "🤖 DevOps Agent\n\n"
            "Usage: /agent <task>\n\n"
            "Examples:\n"
            "• /agent add /stats command\n"
            "• /agent fix bug in context.py\n"
            "• /agent review last commit\n"
            "• /agent refactor claude handler\n"
            "• /agent optimize database queries"
        )
        return

    # Send to agent service
    try:
        await message.answer("🤖 Agent started working...")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT_SERVICE_URL}/agent/command",
                json={
                    "prompt": command_text,
                    "user_id": message.from_user.id,
                    "message_id": message.message_id
                },
                timeout=5.0
            )
            response.raise_for_status()

        # Agent will send updates asynchronously via send_telegram_message()

    except httpx.TimeoutException:
        await message.answer(
            "⚠️ Agent service timeout. Check agent-service logs."
        )
    except httpx.HTTPError as e:
        await message.answer(
            f"❌ Agent service error: {str(e)}"
        )

@router.message(Command("approve_pr"))
async def approve_pr_command(message: Message):
    """Approve and merge PR, then deploy"""

    # Security: only owner
    if message.from_user.id != OWNER_ID:
        return

    # Extract PR number
    try:
        pr_number = int(message.text.replace("/approve_pr ", "").strip())
    except ValueError:
        await message.answer("Usage: /approve_pr <number>")
        return

    await message.answer(f"⏳ Merging PR #{pr_number} and deploying...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT_SERVICE_URL}/agent/approve-pr",
                json={
                    "pr_number": pr_number,
                    "user_id": message.from_user.id
                },
                timeout=60.0  # Longer timeout for deployment
            )
            response.raise_for_status()

        # Success message sent by agent service

    except httpx.HTTPError as e:
        await message.answer(
            f"❌ Failed to approve PR: {str(e)}"
        )

@router.message(Command("agent_status"))
async def agent_status_command(message: Message):
    """Check agent service status"""

    # Security: only owner
    if message.from_user.id != OWNER_ID:
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{AGENT_SERVICE_URL}/health",
                timeout=5.0
            )
            response.raise_for_status()

            data = response.json()

            await message.answer(
                f"✅ Agent Service Status\n\n"
                f"Status: {data.get('status', 'unknown')}\n"
                f"Version: {data.get('version', 'unknown')}\n"
                f"Uptime: {data.get('uptime', 'unknown')}"
            )
    except Exception as e:
        await message.answer(
            f"❌ Agent service unavailable: {str(e)}"
        )
```

### 8. Loki Alert Integration

```yaml
# loki/alert-rules.yaml

groups:
  - name: bot_errors
    interval: 30s
    rules:
      - alert: PythonException
        expr: |
          count_over_time({container="bot"} |~ "ERROR|Exception|Traceback" [5m]) > 0
        labels:
          severity: high
          component: bot
        annotations:
          summary: "Error detected in bot container"
          description: "{{ $labels.container }} has errors in logs"

        # Webhook to agent service
        webhook_configs:
          - url: http://agent:8001/agent/auto-fix
            send_resolved: false
            http_config:
              headers:
                Content-Type: application/json
```

**Loki webhook payload parser:**
```python
# agent-service/agent/loki_webhook.py

from fastapi import Request

@app.post("/agent/auto-fix")
async def loki_webhook_handler(request: Request):
    """Handle Loki alert webhook"""

    payload = await request.json()

    # Parse Loki alert
    alerts = payload.get('alerts', [])

    for alert in alerts:
        # Extract error info from logs
        log_lines = alert.get('annotations', {}).get('log_lines', '')

        # Parse traceback
        error_info = parse_traceback(log_lines)

        if error_info:
            # Trigger auto-fix
            error_report = ErrorReport(
                error_id=generate_error_id(),
                summary=error_info['summary'],
                traceback=error_info['traceback'],
                file_path=error_info['file_path'],
                line_number=error_info['line_number'],
                timestamp=alert.get('startsAt')
            )

            await auto_fix_error(error_report)

    return {"status": "processed"}
```

---

## Security

### Critical Security Measures

**1. Owner-Only Access**

All agent operations require owner authentication:

```python
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))

def validate_owner(user_id: int):
    if user_id != OWNER_ID:
        raise HTTPException(403, "Only bot owner can use agent")
```

**2. Protected Files**

Agent cannot modify sensitive files:

```python
PROTECTED_PATHS = [
    "secrets/",
    ".env",
    "*.key",
    "compose.yaml",
    "agent-service/",  # Cannot modify itself
]
```

**3. Dangerous Command Blocking**

Prevent destructive operations:

```python
RESTRICTED_OPERATIONS = [
    "rm -rf",
    "shutdown",
    "reboot",
    "chmod 777",
]
```

**4. Review Before Merge**

Agent **always** creates PRs, never commits directly to main:
- Owner reviews code changes
- Owner manually approves via `/approve_pr`
- Git history preserved
- Rollback possible

**5. Audit Logging**

All agent operations logged:

```python
logger.info(
    "agent_operation",
    user_id=user_id,
    tool_name=tool_name,
    file_path=file_path,
    command=command,
    pr_number=pr_number
)
```

**6. Rate Limiting**

Prevent abuse:
- Max 10 agent commands per hour per owner
- Max 5 auto-fixes per hour
- Cooldown after failed operations

**7. Docker Socket Isolation**

Agent has read-only Docker socket access:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro  # Read-only
```

Can only restart specific containers, not arbitrary operations.

**8. GitHub Token Scope**

GitHub token should have minimal permissions:
- `repo` scope (for PRs)
- No admin/delete permissions
- Regularly rotated

---

## Implementation Tasks

### Phase 2.2 Tasks

**Infrastructure:**
- [ ] Agent service Docker container setup
- [ ] Claude Code CLI installation in container
- [ ] Agent SDK installation (Python or TypeScript)
- [ ] Shared volume configuration (/workspace)
- [ ] Docker socket access setup
- [ ] FastAPI server implementation
- [ ] Health check endpoint

**Agent Core:**
- [ ] Command handler implementation
- [ ] Agent SDK query integration
- [ ] Streaming progress to Telegram
- [ ] Result parsing (PR URLs, summaries)
- [ ] Error handling and retries

**GitHub Integration:**
- [ ] GitHub API client (create PR, merge, comment)
- [ ] Branch management
- [ ] Commit message templates
- [ ] PR description templates
- [ ] Webhook handling (optional)

**Telegram Integration:**
- [ ] /agent command handler
- [ ] /approve_pr command handler
- [ ] /agent_status command handler
- [ ] Owner-only access control
- [ ] Progress message streaming
- [ ] PR preview formatting

**Auto-Fix System:**
- [ ] Loki alert webhook endpoint
- [ ] Traceback parser
- [ ] Error classification
- [ ] Auto-fix prompt templates
- [ ] Fix verification (tests)
- [ ] Notification system

**Security:**
- [ ] Owner authentication
- [ ] Protected paths validation
- [ ] Dangerous command blocking
- [ ] Audit logging
- [ ] Rate limiting
- [ ] Docker socket isolation
- [ ] GitHub token rotation

**Docker Control:**
- [ ] Container restart logic
- [ ] Health check waiting
- [ ] Logs retrieval
- [ ] Rollback mechanism (if deploy fails)

**Testing:**
- [ ] Unit tests: security module
- [ ] Unit tests: GitHub client
- [ ] Integration tests: agent commands
- [ ] Integration tests: auto-fix flow
- [ ] End-to-end tests: full cycle
- [ ] Load tests: concurrent operations
- [ ] Security tests: protected files, owner-only

**Documentation:**
- [ ] Update CLAUDE.md with Phase 2.2
- [ ] Agent commands reference
- [ ] Security guidelines
- [ ] Troubleshooting guide
- [ ] Example prompts

**Monitoring:**
- [ ] Agent operation metrics
- [ ] Auto-fix success rate
- [ ] PR creation/merge tracking
- [ ] Error classification stats
- [ ] Cost tracking (Agent SDK usage)

---

## Cost Estimation

### Agent SDK Usage Costs

**Per Operation:**

| Operation Type | Tokens | Cost | Notes |
|----------------|--------|------|-------|
| Simple bug fix | 50K-100K | $0.10-0.20 | Read file, identify, fix |
| New feature (small) | 100K-200K | $0.20-0.40 | Handler + repository |
| New feature (medium) | 200K-400K | $0.40-0.80 | Multiple files, tests |
| Code review | 50K-150K | $0.10-0.30 | Read + analyze |
| Refactoring | 150K-300K | $0.30-0.60 | Multiple files |

**Monthly Estimates:**

**Light usage (hobbyist):**
- 5 auto-fixes/month: $0.50-1.00
- 10 manual features: $2.00-4.00
- 5 code reviews: $0.50-1.50
- **Total: ~$3-7/month**

**Medium usage (active development):**
- 20 auto-fixes/month: $2.00-4.00
- 30 manual features: $6.00-12.00
- 15 code reviews: $1.50-4.50
- **Total: ~$10-20/month**

**Heavy usage (production + active):**
- 50 auto-fixes/month: $5.00-10.00
- 50 features: $10.00-20.00
- 30 reviews: $3.00-9.00
- **Total: ~$18-40/month**

**Cost savings:**
- Developer time saved: **Hours per week**
- Instant bug fixes: **Reduced downtime**
- Automated code review: **Better code quality**

**ROI:** Even at $40/month, saves significant developer time.

---

## Related Documents

- **[phase-2.1-payment-system.md](phase-2.1-payment-system.md)** - Payment system (prerequisite)
- **[phase-1.5-multimodal-tools.md](phase-1.5-multimodal-tools.md)** - Tools architecture
- **[CLAUDE.md](../CLAUDE.md)** - Project overview
- **[Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)** - Official documentation

---

## Future Enhancements (Phase 3+)

**Advanced Features:**
- **Multi-agent workflows**: Specialized agents (reviewer, optimizer, tester)
- **Automated testing**: Agent runs tests before creating PR
- **Performance profiling**: Agent identifies slow queries/endpoints
- **Security scanning**: Agent checks for vulnerabilities
- **Documentation generation**: Agent updates docs when code changes
- **Dependency updates**: Agent creates PRs for package updates
- **A/B testing**: Agent deploys canary versions for testing

**Integration:**
- **Slack notifications**: Team alerts for agent actions
- **Jira integration**: Agent creates tickets, updates status
- **CI/CD integration**: Agent triggers pipelines
- **Metrics dashboard**: Agent operation analytics

**AI Improvements:**
- **Learning from rejections**: Improve based on rejected PRs
- **Pattern recognition**: Learn common bugs/fixes
- **Predictive fixes**: Prevent issues before they occur
- **Code style learning**: Adapt to team's coding style
