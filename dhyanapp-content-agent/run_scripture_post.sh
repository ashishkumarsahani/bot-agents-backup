#!/bin/bash
# Scripture Daily Post Generator (Aditya Karn) - Alternate-day posting.
# Idempotent: the script internally skips on rest days and same-day re-runs.

# Agent enablement check
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python /home/admin/bot_agents/dhyanapp-content-agent/check_agent.py scripture-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Scripture Post Bot is disabled, skipping."
    exit 0
}

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python scripture_post_generator.py --run-now
