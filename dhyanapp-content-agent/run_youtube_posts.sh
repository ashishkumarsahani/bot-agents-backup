#!/bin/bash
# YouTube-sourced Post Generator - Runs daily.
# Picks one eligible bot (3-day cooldown per bot), fetches a short from its
# assigned YouTube channels, generates a post from the transcript via gpt-5-mini,
# and writes it to MongoDB. Engagement is handled automatically by dhyan-triggers.
#
# Optional config (env vars, or same-named keys in Mongo config/secrets):
#   YT_DLP_PATH                 override the yt-dlp binary location (auto-detected otherwise)
#   YT_DLP_PROXY                route yt-dlp through a proxy if YouTube blocks the server IP
#                               e.g. http://user:pass@host:port or socks5://host:port
#   YT_DLP_COOKIES              path to a cookies.txt exported for youtube.com
#   YT_DLP_COOKIES_FROM_BROWSER browser name for yt-dlp --cookies-from-browser (e.g. chrome)
#   ALERT_WEBHOOK_URL           Slack-compatible webhook; fires on blocked/exhausted runs
# Health heartbeat is written to Mongo bot_config/_id=youtube_post_health (last_success_at).

# Agent enablement check
/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python /Users/epilepto/bot_agents/dhyanapp-content-agent/check_agent.py youtube-post-bot || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] YouTube Post Bot is disabled, skipping."
    exit 0
}

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_post_generator.py
