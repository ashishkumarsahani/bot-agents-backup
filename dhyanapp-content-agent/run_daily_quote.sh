#!/bin/bash
# Daily Quote Poster - Runs at 6 AM IST

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py daily-quote-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily Quote Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python -c "from scheduler_service import generate_and_post_quote; generate_and_post_quote()"
