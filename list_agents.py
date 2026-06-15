#!/usr/bin/env python3
"""List all DhyanApp agents — bot agents, event agents, and trigger services."""

import json
import subprocess
import os
from datetime import datetime
from pathlib import Path

ENABLED_STATE_FILE = Path("/home/admin/bot_agents/dhyanapp-content-agent/agents_enabled.json")


def load_enabled_state():
    try:
        if ENABLED_STATE_FILE.exists():
            with open(ENABLED_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

AGENTS = [
    {
        "id": "persona-quote-bot",
        "name": "Persona Quote Bot",
        "description": "Generates daily spiritual quotes with images from rotating bot personas",
        "script": "/home/admin/bot_agents/dhyanapp-content-agent/persona_quote_generator.py",
        "cron": "30 0 * * * (6:00 AM IST daily)",
        "log": "/home/admin/bot_agents/dhyanapp-content-agent/quote_cron.log",
        "type": "cron",
    },
    {
        "id": "persona-post-bot",
        "name": "Persona Post Bot",
        "description": "Generates daily spiritual posts with AI images from rotating bot personas",
        "script": "/home/admin/bot_agents/dhyanapp-content-agent/persona_post_generator.py",
        "cron": "30 12 * * * (6:00 PM IST daily)",
        "log": "/home/admin/bot_agents/dhyanapp-content-agent/post_cron.log",
        "type": "cron",
    },
    {
        "id": "gita-post-bot",
        "name": "Bhagavad Gita Post Bot",
        "description": "Posts one Krishna-spoken verse per day with AI infographic images",
        "script": "/home/admin/bot_agents/dhyanapp-content-agent/gita_post_generator.py",
        "cron": "0 7 * * * (7:00 AM IST daily)",
        "log": "/home/admin/bot_agents/dhyanapp-content-agent/gita_cron.log",
        "type": "cron",
    },
    {
        "id": "scripture-post-bot",
        "name": "Scripture Post Bot (Aditya Karn)",
        "description": "Posts from non-Gita Hindu scriptures on alternate days with tone-matched reflections",
        "script": "/home/admin/bot_agents/dhyanapp-content-agent/scripture_post_generator.py",
        "cron": "0 8 * * * (8:00 AM IST, alternate-day logic)",
        "log": "/home/admin/bot_agents/dhyanapp-content-agent/scripture_cron.log",
        "type": "cron",
    },
    {
        "name": "Bot Engagement (Trigger)",
        "description": "Auto-likes and AI comments on new posts via Celery tasks",
        "script": "/home/admin/dhyan-triggers/src/dhyan_triggers/tasks/bot_engagement.py",
        "cron": "Event-driven (on post insert)",
        "log": "Celery worker logs",
        "type": "trigger",
        "process_grep": "celery.*p1_social",
    },
    {
        "name": "Change Stream Watcher",
        "description": "Real-time MongoDB change stream watcher dispatching events to Celery",
        "script": "/home/admin/dhyan-triggers/src/dhyan_triggers/watcher/main.py",
        "cron": "Persistent service",
        "log": "structlog (stdout)",
        "type": "service",
        "process_grep": "dhyan_triggers.watcher.main",
    },
    {
        "name": "Celery Beat Scheduler",
        "description": "Coordinates scheduled Celery tasks across all queues",
        "script": "/home/admin/dhyan-triggers/src/dhyan_triggers/celery_app.py",
        "cron": "Persistent service",
        "log": "Celery beat logs",
        "type": "service",
        "process_grep": "celery.*beat",
    },
    {
        "name": "Migration Watcher (Legacy)",
        "description": "Legacy change stream watcher for dhyanapp-services migration",
        "script": "/home/admin/dhyanapp-services/migration/services/run_watcher.py",
        "cron": "Persistent service",
        "log": "stdout",
        "type": "service",
        "process_grep": "migration.services.run_watcher",
    },
]


def check_process(grep_pattern):
    """Check if a process matching the pattern is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-af", grep_pattern],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l and "pgrep" not in l]
        if lines:
            pid = lines[0].split()[0]
            return True, pid
        return False, None
    except Exception:
        return False, None


def get_log_tail(log_path, lines=1):
    """Get last line of a log file."""
    if not os.path.exists(log_path):
        return "Log file not found"
    try:
        result = subprocess.run(
            ["tail", f"-{lines}", log_path],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "Could not read log"


def get_log_size(log_path):
    """Get log file size."""
    if not os.path.exists(log_path):
        return "N/A"
    size = os.path.getsize(log_path)
    if size > 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    elif size > 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def main():
    print(f"\n{'=' * 70}")
    print(f"  DHYANAPP AGENTS STATUS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}\n")

    enabled_state = load_enabled_state()

    for i, agent in enumerate(AGENTS, 1):
        # Determine status
        if agent["type"] in ("service", "trigger"):
            grep = agent.get("process_grep", "")
            running, pid = check_process(grep) if grep else (False, None)
            if running:
                status = f"\033[92mRUNNING\033[0m (PID {pid})"
            else:
                status = "\033[91mSTOPPED\033[0m"
        else:
            # Cron job — check enabled state, script existence
            agent_id = agent.get("id")
            is_enabled = enabled_state.get(agent_id, True) if agent_id else True
            script_exists = os.path.exists(agent["script"])
            if not is_enabled:
                status = "\033[91mDISABLED\033[0m"
            elif not script_exists:
                status = "\033[91mSCRIPT MISSING\033[0m"
            else:
                status = "\033[93mCRON SCHEDULED\033[0m"

        # Log info
        log_path = agent["log"]
        log_size = get_log_size(log_path) if os.path.exists(log_path) else ""

        print(f"  {i}. {agent['name']}")
        print(f"     {agent['description']}")
        print(f"     Status:   {status}")
        print(f"     Schedule: {agent['cron']}")
        print(f"     Script:   {agent['script']}")
        if os.path.exists(log_path):
            print(f"     Log:      {log_path} ({log_size})")
            last_line = get_log_tail(log_path)
            if last_line:
                print(f"     Last log: {last_line[:90]}")
        print()

    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
