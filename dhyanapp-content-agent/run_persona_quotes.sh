#!/bin/bash
# Persona-Based Quote Generator - Runs daily at 6 AM IST
# Posts ONE quote from a rotating bot account
# Engagement is handled by cloud functions

# Agent enablement check
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python /home/admin/bot_agents/dhyanapp-content-agent/check_agent.py persona-quote-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Persona Quote Bot is disabled, skipping."
    exit 0
}

cd /home/admin/bot_agents/dhyanapp-content-agent

# Generate and post the daily quote (no engagement - handled by cloud functions)
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_quote_generator.py --run-now --single --no-engagement
