#!/bin/bash
# Festival Post Bot - Runs daily at 5 AM IST with random delay (posts between 5-10 AM IST)

# Agent enablement check
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python /home/admin/bot_agents/dhyanapp-content-agent/check_agent.py festival-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Festival Post Bot is disabled, skipping."
    exit 0
}

cd /home/admin/bot_agents/dhyanapp-content-agent
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python festival_post_scheduler.py --run-random
