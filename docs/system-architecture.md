# System Architecture

## Overview

The DhyanApp bot system has two main execution environments that work together:

1. **Local Server** (cron jobs) - Generates and publishes posts/quotes
2. **Firebase Cloud Functions** - Handles automatic engagement (likes and comments)

A third component handles engagement with real user posts:

3. **Local User Engagement Service** - Detects and engages with posts from real users

## Architecture Diagram

```
                          LOCAL SERVER (Cron Jobs)
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  6:00 AM IST                           6:00 PM IST                  │
│  ┌──────────────────┐                  ┌──────────────────┐         │
│  │ run_persona_     │                  │ run_persona_     │         │
│  │ quotes.sh        │                  │ posts.sh         │         │
│  └────────┬─────────┘                  └────────┬─────────┘         │
│           │                                     │                    │
│           ▼                                     ▼                    │
│  ┌──────────────────┐                  ┌──────────────────┐         │
│  │ persona_quote_   │                  │ persona_post_    │         │
│  │ generator.py     │                  │ generator.py     │         │
│  │                  │                  │                  │         │
│  │ 1. Rotate bot    │                  │ 1. Rotate bot    │         │
│  │ 2. Check festival│                  │ 2. Check festival│         │
│  │ 3. Web search    │                  │ 3. Web search    │         │
│  │ 4. Generate text │                  │ 4. Generate text │         │
│  │ 5. Create image  │                  │ 5. Create image  │         │
│  │ 6. Publish       │                  │ 6. Publish       │         │
│  └────────┬─────────┘                  └────────┬─────────┘         │
│           └──────────────┬──────────────────────┘                    │
│                          ▼                                           │
│                 ┌──────────────┐                                     │
│                 │  Firestore   │                                     │
│                 │ posts/{id}   │                                     │
│                 └──────┬───────┘                                     │
└────────────────────────┼─────────────────────────────────────────────┘
                         │
                         │ Firestore onCreate Trigger
                         ▼
              FIREBASE CLOUD FUNCTIONS
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │                  onPostCreated                              │      │
│  │                                                            │      │
│  │  1. Load bot accounts from botConfig/accounts              │      │
│  │  2. Exclude the post author                                │      │
│  │  3. Schedule 7 likes via Cloud Tasks (5-min intervals)     │      │
│  │  4. Schedule 2 comments via Cloud Tasks (1-min, 16-min)    │      │
│  └──────────────────────┬─────────────────────────────────────┘      │
│                         │                                            │
│                         ▼                                            │
│               ┌──────────────────┐                                   │
│               │   Cloud Tasks    │                                   │
│               │   Queue          │                                   │
│               └────────┬─────────┘                                   │
│                        │                                             │
│           ┌────────────┴────────────┐                                │
│           ▼                         ▼                                │
│  ┌─────────────────┐     ┌──────────────────┐                       │
│  │  processLike    │     │  processComment  │                       │
│  │                 │     │                  │                       │
│  │ Add like +      │     │ 1. Theme check   │                       │
│  │ view to post    │     │ 2. Web search    │                       │
│  └─────────────────┘     │ 3. Generate text │                       │
│                          │ 4. Add comment   │                       │
│                          └──────────────────┘                       │
└──────────────────────────────────────────────────────────────────────┘
```

## User Post Engagement (Separate Flow)

```
┌──────────────────────────────────────────────────────────────────────┐
│                  USER POST ENGAGEMENT (Local)                        │
│                                                                      │
│  ┌──────────────────────┐      ┌─────────────────────────────┐      │
│  │ user_post_           │      │ user_engagement_state.json  │      │
│  │ engagement.py        │◄────►│                             │      │
│  │                      │      │ last_checked_ms: ...        │      │
│  │ 1. Query new posts   │      │ last_run_stats: {...}       │      │
│  │    since last check  │      └─────────────────────────────┘      │
│  │ 2. Filter user posts │                                           │
│  │ 3. Analyze with      │                                           │
│  │    GPT-4 Vision      │                                           │
│  │ 4. All 8 bots like   │                                           │
│  │ 5. 2 random bots     │                                           │
│  │    comment            │                                           │
│  └──────────────────────┘                                           │
└──────────────────────────────────────────────────────────────────────┘
```

## External Services

| Service | Purpose |
|---------|---------|
| **OpenAI GPT-4o-mini** | Content generation, comment generation |
| **OpenAI GPT-4 Vision** | Image analysis for user post engagement |
| **SerperDev API** | Web search for post content and quotes |
| **GPT Web Search** | Web search in cloud functions (via OpenAI responses API) |
| **DhyanApp Services API** | Image generation for posts and quotes |
| **Firebase Firestore** | Database for posts, comments, likes, config |
| **Firebase Storage** | Image hosting |
| **Google Cloud Tasks** | Delayed task scheduling for engagement |

## Key Files

| File | Location | Purpose |
|------|----------|---------|
| `persona_post_generator.py` | `dhyanapp-content-agent/` | Daily content post generation |
| `persona_quote_generator.py` | `dhyanapp-content-agent/` | Daily quote generation |
| `engagement_service.py` | `dhyanapp-content-agent/` | Local engagement service (bot-to-bot) |
| `user_post_engagement.py` | `dhyanapp-content-agent/` | Engagement with real user posts |
| `firestore_service.py` | `dhyanapp-content-agent/` | Firestore connection and operations |
| `bot_accounts.json` | `dhyanapp-content-agent/` | Bot persona configurations |
| `botEngagement.js` | `cloud-functions/` | Cloud function engagement logic |
| `index.js` | `cloud-functions/` | Cloud function exports |
