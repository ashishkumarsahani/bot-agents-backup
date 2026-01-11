#!/bin/bash
# Festival Post Bot - Runs daily at 5 AM IST with random delay (posts between 5-10 AM IST)

cd /home/admin/bot_agents/dhyanapp-content-agent
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python festival_post_scheduler.py --run-random
