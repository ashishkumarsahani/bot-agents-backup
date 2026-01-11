#!/bin/bash
# Persona-Based Quote Generator - Runs daily at 6 AM IST
# Posts ONE quote from a rotating bot account with engagement

cd /home/admin/bot_agents/dhyanapp-content-agent
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_quote_generator.py --run-now --single
