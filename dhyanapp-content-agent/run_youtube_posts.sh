#!/bin/bash
# YouTube-sourced Post Generator - Runs daily.
# Picks one eligible bot (3-day cooldown per bot), fetches a short from its
# assigned YouTube channels, generates a post from the transcript via gpt-5-mini,
# and writes it to MongoDB. Engagement is handled automatically by dhyan-triggers.

cd /home/admin/bot_agents/dhyanapp-content-agent

/home/admin/bot_agents/dhyanapp-content-agent/.venv/bin/python youtube_post_generator.py
