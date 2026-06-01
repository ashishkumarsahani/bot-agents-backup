#!/bin/bash
# Tattvaloka Magazine Post Generator - Alternate-day posting.
# Idempotent: the script internally skips on rest days and same-day re-runs.

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python magazine_post_generator.py --run-now
