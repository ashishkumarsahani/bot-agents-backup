#!/bin/bash
# Daily self-healing sweep: regenerate bot images that failed in the last 5 days.
# Idempotent: skips items that already have an image. Safe to re-run.

cd /Users/epilepto/bot_agents/dhyanapp-content-agent

/Users/epilepto/bot_agents/dhyanapp-content-agent/.venv/bin/python heal_failed_images.py --days 5 --attempts 3 \
    >> /Users/epilepto/bot_agents/dhyanapp-content-agent/heal_images_cron.log 2>&1
