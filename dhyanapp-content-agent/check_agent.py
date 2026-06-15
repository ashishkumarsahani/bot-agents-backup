#!/usr/bin/env python3
"""Exit 0 if agent is enabled, 1 if disabled. Used by runner shell scripts."""

import json
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent / "agents_enabled.json"


def main():
    if len(sys.argv) < 2:
        print("Usage: check_agent.py <agent_id>")
        sys.exit(2)
    agent_id = sys.argv[1]
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            enabled = state.get(agent_id, True)
        else:
            enabled = True
    except Exception:
        enabled = True
    sys.exit(0 if enabled else 1)


if __name__ == "__main__":
    main()
