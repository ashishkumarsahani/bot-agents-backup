#!/bin/bash
# Persona-Based Post Generator - Runs daily at 6 PM IST
# Posts ONE post from a rotating bot account
# Engagement is handled by cloud functions

cd /home/admin/bot_agents/dhyanapp-content-agent

# Generate and post the daily post (no engagement - handled by cloud functions)
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_post_generator.py --run-now --single --no-engagement
