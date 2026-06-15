#!/bin/bash
# Tattvaloka Magazine Article Generator - Alternate-day publishing.
# Idempotent: skips on rest days and same-day re-runs.

# Agent enablement check
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python /home/admin/bot_agents/dhyanapp-content-agent/check_agent.py magazine-article-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Magazine Article Bot is disabled, skipping."
    exit 0
}

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python magazine_article_generator.py --run-now
