#!/bin/bash
# Persona-Based Post Generator - Runs daily at 6 PM IST
# Posts ONE post from a rotating bot account with engagement

cd /home/admin/bot_agents/dhyanapp-content-agent
/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python persona_post_generator.py --run-now --single
