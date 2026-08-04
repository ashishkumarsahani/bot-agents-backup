#!/bin/bash
# Tattvaloka Magazine Post Generator - Alternate-day posting.
# Idempotent: the script internally skips on rest days and same-day re-runs.

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py magazine-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Magazine Post Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python magazine_post_generator.py --run-now
