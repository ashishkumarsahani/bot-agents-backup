#!/bin/bash
# Bhagavad Gita Daily Verse Post Generator - Runs once each morning.
# Idempotent per day: re-runs on the same date are no-ops.

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python gita_post_generator.py --run-now
