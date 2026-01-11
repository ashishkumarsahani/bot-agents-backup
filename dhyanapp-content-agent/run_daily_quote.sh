#!/bin/bash
# Daily Quote Poster - Runs at 6 AM IST

cd /home/admin/bot_agents/dhyanapp-content-agent
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python -c "from scheduler_service import generate_and_post_quote; generate_and_post_quote()"
