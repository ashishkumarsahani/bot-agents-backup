#!/bin/bash
# Run ALL bots' community + reels scans (each bot processes its OWN channels).
# Called twice daily (06:30 via com.epilepto.bot_agents, 18:30 via com.dhyanapp
# youtube-community-evening). The generators have built-in dedup, so each bot only
# publishes YouTube community posts / reels that appeared since its last run.

LOGTAG="[all-bots]"
cd /Users/epilepto/bot_agents/dhyanapp-content-agent

echo "[$LOGTAG $(date '+%Y-%m-%d %H:%M:%S')] === All-bots dual run starting ==="

# --- Community posts: every bot with community_channels ---
if /Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python check_agent.py youtube-community-bot; then
    for bot in dhyani yogini jagdish rajesh_ray; do
        echo "[$LOGTAG $(date '+%Y-%m-%d %H:%M:%S')] community scan: $bot"
        /Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_community_post_generator.py --bot "$bot" 2>&1 | tail -3
    done
fi

# --- Reels: every bot with youtube_channels ---
if /Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python check_agent.py youtube-post-bot; then
    for bot in dhyani yogini rahul_dev rajesh_ray jagdish vidur subhasish_sahani sudhanjali_sahani; do
        echo "[$LOGTAG $(date '+%Y-%m-%d %H:%M:%S')] reels scan: $bot"
        /Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_post_generator.py --bot "$bot" 2>&1 | tail -3
    done
fi

echo "[$LOGTAG $(date '+%Y-%m-%d %H:%M:%S')] === All-bots dual run complete ==="