#!/bin/bash
# Tattvaloka Magazine Article Generator - Alternate-day publishing.
# Idempotent: skips on rest days and same-day re-runs.

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python magazine_article_generator.py --run-now
