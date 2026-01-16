#!/bin/bash
# Persona-Based Quote Generator - Runs daily at 6 AM IST
# Posts ONE quote from a rotating bot account with engagement
# Also checks for new user posts and engages with them

cd /home/admin/bot_agents/dhyanapp-content-agent

# Generate and post the daily quote
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_quote_generator.py --run-now --single

# Check for new user posts and engage with them
echo ""
echo "Checking for new user posts..."
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python user_post_engagement.py --run
