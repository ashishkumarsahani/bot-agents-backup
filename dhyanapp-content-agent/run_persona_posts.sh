#!/bin/bash
# Persona-Based Post Generator - Runs daily at 6 PM IST
# Posts ONE post from a rotating bot account
# Engagement is handled by cloud functions

# Agent enablement check
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python /home/admin/bot_agents/dhyanapp-content-agent/check_agent.py persona-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Persona Post Bot is disabled, skipping."
    exit 0
}

cd /home/admin/bot_agents/dhyanapp-content-agent

# Generate and post the daily post (no engagement - handled by cloud functions)
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_post_generator.py --run-now --single --no-engagement
