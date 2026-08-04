#!/bin/bash
# YouTube-sourced Post Generator - Runs daily.
# Picks one eligible bot (3-day cooldown per bot), fetches a short from its
# assigned YouTube channels, generates a post from the transcript via gpt-5-mini,
# and writes it to MongoDB. Engagement is handled automatically by dhyan-triggers.

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py youtube-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] YouTube Post Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_post_generator.py
