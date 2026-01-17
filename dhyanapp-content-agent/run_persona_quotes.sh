#!/bin/bash
# Persona-Based Quote Generator - Runs daily at 6 AM IST
# Posts ONE quote from a rotating bot account
# Engagement is handled by cloud functions

cd /home/admin/bot_agents/dhyanapp-content-agent

# Generate and post the daily quote (no engagement - handled by cloud functions)
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_quote_generator.py --run-now --single --no-engagement
