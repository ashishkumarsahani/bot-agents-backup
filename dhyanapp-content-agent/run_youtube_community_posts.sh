#!/bin/bash
# YouTube Community-post Reposter - Runs daily.
# Picks one eligible bot (3-day cooldown per bot), scrapes the newest Community/
# Posts-tab post that has image(s) from its assigned community_channels via the
# InnerTube API, re-hosts the image(s) on MinIO, and writes a multi-image
# DhyanApp post that copies the text verbatim with a "via @channel" credit.
# Engagement is handled automatically by dhyan-triggers.
#
# Optional config (env vars, or same-named keys in Mongo config/secrets):
#   YT_DLP_PROXY       route InnerTube requests through a proxy if YouTube blocks
#                      the server IP (e.g. http://user:pass@host:port)
#   YT_DLP_COOKIES     path to a cookies.txt exported for youtube.com
#   ALERT_WEBHOOK_URL  Slack-compatible webhook; fires on blocked/failed runs
# Health heartbeat -> Mongo bot_config/_id=youtube_community_health (last_success_at).

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py youtube-community-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] YouTube Community Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_community_post_generator.py
