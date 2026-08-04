#!/bin/bash
# Bhagavad Gita Daily Verse Post Generator - Runs once each morning.
# Idempotent per day: re-runs on the same date are no-ops.

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py gita-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bhagavad Gita Post Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python gita_post_generator.py --run-now
