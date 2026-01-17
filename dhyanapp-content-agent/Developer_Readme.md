# DhyanApp Bot Content Agent - Developer Documentation

## Overview

This system automates content generation and engagement for DhyanApp, a spiritual meditation app. It consists of two main components:

1. **Local Cron Jobs** (this server) - Generate daily posts and quotes
2. **Firebase Cloud Functions** - Handle automatic engagement (likes/comments)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL SERVER (Cron Jobs)                          │
│                                                                             │
│  ┌─────────────────────┐       ┌─────────────────────┐                     │
│  │  run_persona_quotes │       │  run_persona_posts  │                     │
│  │    (6:00 AM IST)    │       │    (6:00 PM IST)    │                     │
│  └──────────┬──────────┘       └──────────┬──────────┘                     │
│             │                             │                                 │
│             ▼                             ▼                                 │
│  ┌─────────────────────┐       ┌─────────────────────┐                     │
│  │persona_quote_gener- │       │persona_post_genera- │                     │
│  │     ator.py         │       │       tor.py        │                     │
│  └──────────┬──────────┘       └──────────┬──────────┘                     │
│             │                             │                                 │
│             └──────────────┬──────────────┘                                 │
│                            ▼                                                │
│                   ┌────────────────┐                                        │
│                   │   Firestore    │                                        │
│                   │ posts/{postId} │                                        │
│                   └────────┬───────┘                                        │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │
                             │ Firestore Trigger
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FIREBASE CLOUD FUNCTIONS                               │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      onPostCreated (Firestore Trigger)               │   │
│  │                                                                      │   │
│  │  1. Detects new post in posts/{postId}                              │   │
│  │  2. Gets bot accounts from botConfig/accounts                        │   │
│  │  3. Excludes the poster from engagement                              │   │
│  │  4. Schedules likes via Cloud Tasks (5-min intervals)                │   │
│  │  5. Schedules 2 comments via Cloud Tasks (1-min, 16-min delays)     │   │
│  └──────────────────────────┬──────────────────────────────────────────┘   │
│                             │                                               │
│                             ▼                                               │
│                   ┌─────────────────┐                                       │
│                   │  Cloud Tasks    │                                       │
│                   │  Queue          │                                       │
│                   └────────┬────────┘                                       │
│                            │                                                │
│              ┌─────────────┴─────────────┐                                  │
│              ▼                           ▼                                  │
│  ┌─────────────────────┐     ┌─────────────────────┐                       │
│  │    processLike      │     │   processComment    │                       │
│  │  (HTTP endpoint)    │     │  (HTTP endpoint)    │                       │
│  │                     │     │                     │                       │
│  │ Adds like to post   │     │ 1. Analyzes post    │                       │
│  │ from bot account    │     │ 2. Gets GPT comment │                       │
│  └─────────────────────┘     │ 3. Adds to Firestore│                       │
│                              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Bot Accounts

The system uses 8 bot accounts, each with a unique spiritual persona:

| Bot Name | User ID | Persona | Languages |
|----------|---------|---------|-----------|
| **Dhyani** | `7es9AYnaW7afNtMeOBtXl8Z2ILF3` | Advaita Vedanta & Bhakti Yoga practitioner | Hindi, English |
| **Yogini** | `N7wdlwvkkWf4ruDSArgPwxoDC493` | Tantric sadhika, Sri Vidya follower | Hindi, English |
| **Jagdish** | `C3mGbHqnzWhvCPpW4XItfl7cmvL2` | Vaishnava devotee, Krishna bhakti | Hindi, English |
| **Vidur** | `OowZ26AOxPR63y0XR0Sm3eEdYfG3` | Epic storyteller (Mahabharata, Ramayana) | Hindi, English |
| **Rahul Dev** | `8tQFmQ6cmvbfZ756tcbRivd3J5y1` | Sant Parampara, Kabir follower | Hindi only |
| **Subhasish Sahani** | `d8QbuQ4S5Whf1VMnp9i4SQaOnep2` | Kriya Yoga practitioner | Hindi, English |
| **Sudhanjali Sahani** | `xvGsVZPmPtfeJJAPim0biICdwom1` | Ramana Maharshi follower, self-inquiry | Hindi, English |
| **Rajesh Ray** | `nZS5gEEmEMMGGmIp0t3Ks1qHTfM2` | Hindutva advocate, RSS philosophy | Hindi, English |

Bot account configuration is stored in:
- Local: `bot_accounts.json`
- Firestore: `botConfig/accounts`

---

## Component 1: Local Cron Jobs (Post/Quote Generation)

### Location
```
/home/admin/bot_agents/dhyanapp-content-agent/
```

### Cron Schedule
```bash
# Daily quote at 6:00 AM IST (00:30 UTC)
30 0 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_quotes.sh >> quote_cron.log 2>&1

# Daily post at 6:00 PM IST (12:30 UTC)
30 12 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_posts.sh >> post_cron.log 2>&1
```

### Scripts

#### `run_persona_quotes.sh`
```bash
#!/bin/bash
cd /home/admin/bot_agents/dhyanapp-content-agent
.venv/bin/python persona_quote_generator.py --run-now --single --no-engagement
```

#### `run_persona_posts.sh`
```bash
#!/bin/bash
cd /home/admin/bot_agents/dhyanapp-content-agent
.venv/bin/python persona_post_generator.py --run-now --single --no-engagement
```

### Post Generation Flow

1. **Bot Selection**: Uses round-robin rotation stored in `rotation_state.json` / `quote_rotation_state.json`
2. **Content Generation**:
   - Searches web for authentic quotes/teachings using SerperDev API
   - Falls back to AI-generated content if search fails
   - Generates persona-specific commentary using GPT-4o-mini
3. **Image Generation**:
   - Creates background image via dhyanapp-services API
   - Adds text overlay with quote and attribution
4. **Publishing**:
   - Uploads image to Firebase Storage
   - Creates post document in Firestore `posts` collection

### Key Files

| File | Purpose |
|------|---------|
| `persona_quote_generator.py` | Generates daily quote posts |
| `persona_post_generator.py` | Generates daily content posts |
| `firestore_service.py` | Firestore connection and operations |
| `bot_accounts.json` | Bot account configurations |
| `rotation_state.json` | Tracks which bot posts next (posts) |
| `quote_rotation_state.json` | Tracks which bot posts next (quotes) |

### Command Line Options

```bash
# Generate single quote (production)
python persona_quote_generator.py --run-now --single --no-engagement

# Generate quote with engagement (testing)
python persona_quote_generator.py --run-now --single

# Preview without posting
python persona_quote_generator.py --preview

# Generate for specific account
python persona_quote_generator.py --account dhyani --run-now
```

---

## Component 2: Firebase Cloud Functions (Automatic Engagement)

### Location
```
/home/admin/dhyanapp-services/cloud-functions/functions/botEngagement.js
```

### Cloud Functions

| Function | Trigger | Purpose |
|----------|---------|---------|
| `onPostCreated` | Firestore `posts/{postId}` created | Initiates engagement workflow |
| `processLike` | HTTP (via Cloud Tasks) | Adds like from a bot account |
| `processComment` | HTTP (via Cloud Tasks) | Generates and adds AI comment |

### Engagement Flow

```
New Post Created
      │
      ▼
onPostCreated triggers
      │
      ├── Get all bot accounts from Firestore
      │
      ├── Exclude the post creator from engagement
      │
      ├── Schedule LIKES via Cloud Tasks
      │   └── 7 bots × 5-minute intervals = 0, 5, 10, 15, 20, 25, 30 min
      │
      └── Schedule COMMENTS via Cloud Tasks
          ├── Bot 1: 1 minute delay
          └── Bot 2: 16 minute delay
```

### Like Processing (`processLike`)

1. Receives task from Cloud Tasks queue
2. Verifies post still exists and isn't deleted
3. Adds like document to `posts/{postId}/Likes/{botUserId}`
4. `handleLikeCreated` function increments `likeCount`

### Comment Processing (`processComment`)

1. Receives task from Cloud Tasks queue
2. Fetches post content and image
3. Analyzes image using GPT-4 Vision (if present)
4. Gets existing comments for context
5. Generates persona-appropriate comment using GPT-4o-mini
6. Adds comment to `posts/{postId}/Comments/{commentId}`
7. `handleCommentCreated` function increments `commentCount`

### Comment Generation Prompt

The system generates comments that:
- Match the bot's persona and conversational style
- Reference teachings from the bot's spiritual tradition
- Are 10-40 words in length
- Don't repeat what other commenters have said
- Use Hindi or English based on bot's language settings

---

## Firestore Collections

### `posts/{postId}`
Main posts collection where bot-generated and user posts are stored.

```javascript
{
  content: "Post text...",
  createdBy: "userId",
  creatorName: "Bot Name",
  createdAt: 1234567890000,  // milliseconds
  imageUrl: "https://...",
  likeCount: 5,
  commentCount: 3,
  _botGenerated: true,  // Flag for bot posts
  // ... other fields
}
```

### `posts/{postId}/Likes/{userId}`
```javascript
{
  userId: "userId",
  timestamp: 1234567890000
}
```

### `posts/{postId}/Comments/{commentId}`
```javascript
{
  comment: "Comment text...",
  commentId: "timestamp+userId",
  createdBy: "userId",
  createdAt: 1234567890000,
  commentLikesCount: 0,
  repliedTo: null
}
```

### `botConfig/accounts`
Mirror of `bot_accounts.json` for cloud function access.

### `botState/rotation`
Tracks rotation state for post/quote generation.

### `config/secrets`
Stores API keys (OPENAI_API_KEY, SERPER_API_KEY, etc.)

---

## Deployment

### Local Cron Jobs
Cron jobs are already configured. To verify:
```bash
crontab -l
```

### Cloud Functions
```bash
cd /home/admin/dhyanapp-services/cloud-functions
firebase deploy --only functions:onPostCreated,functions:processComment,functions:processLike --project dhyanapp-90de4
```

---

## Monitoring

### Local Logs
```bash
# Quote generation logs
tail -f /home/admin/bot_agents/dhyanapp-content-agent/quote_cron.log

# Post generation logs
tail -f /home/admin/bot_agents/dhyanapp-content-agent/post_cron.log
```

### Cloud Function Logs
```bash
firebase functions:log --project dhyanapp-90de4 --only onPostCreated
firebase functions:log --project dhyanapp-90de4 --only processComment
firebase functions:log --project dhyanapp-90de4 --only processLike
```

### Check Today's Posts
```bash
cd /home/admin/bot_agents/dhyanapp-content-agent
.venv/bin/python -c "
from firestore_service import get_firestore_service
from datetime import datetime, timezone

service = get_firestore_service()
posts = service.get_recent_quotes(10)
for p in posts:
    dt = datetime.fromtimestamp(p.get('createdAt', 0) / 1000)
    print(f\"{dt.strftime('%Y-%m-%d %H:%M')} - {p.get('creatorName')}: {p.get('content', '')[:50]}...\")
"
```

---

## Manual Operations

### Run Quote Generation Manually
```bash
cd /home/admin/bot_agents/dhyanapp-content-agent
./run_persona_quotes.sh
```

### Run Post Generation Manually
```bash
cd /home/admin/bot_agents/dhyanapp-content-agent
./run_persona_posts.sh
```

### Sync Bot Accounts to Firestore
```bash
cd /home/admin/bot_agents/dhyanapp-content-agent
.venv/bin/python -c "
import json
from firestore_service import get_firestore_service

with open('bot_accounts.json') as f:
    data = json.load(f)

service = get_firestore_service()
service.db.collection('botConfig').document('accounts').set({'accounts': data['accounts']})
print('Bot accounts synced to Firestore')
"
```

---

## Troubleshooting

### Posts not being generated
1. Check cron is running: `crontab -l`
2. Check logs: `tail -50 quote_cron.log`
3. Verify Firebase credentials: `cat firebase_credentials.json | head -5`
4. Run manually to see errors: `./run_persona_quotes.sh`

### Engagement not working
1. Check cloud function logs: `firebase functions:log --project dhyanapp-90de4 --only onPostCreated`
2. Verify Cloud Tasks queue exists in GCP Console
3. Check `botConfig/accounts` document exists in Firestore
4. Verify `config/secrets` has `OPENAI_API_KEY`

### Bot account issues
1. Verify user IDs match in Firebase Auth
2. Check `bot_accounts.json` is in sync with Firestore `botConfig/accounts`
3. Ensure bot users exist in `users` collection

---

## Environment Variables

### Local `.env`
```
FIREBASE_CREDENTIALS_PATH=firebase_credentials.json
OPENAI_API_KEY=sk-...
SERPER_API_KEY=...
```

### Firestore `config/secrets`
```javascript
{
  OPENAI_API_KEY: "sk-...",
  SERPER_API_KEY: "...",
  SERVICES_PASSWORD: "..."
}
```

---

## Dependencies

### Python (Local)
- firebase-admin
- openai
- pillow
- requests
- python-dotenv

### Node.js (Cloud Functions)
- firebase-functions
- firebase-admin
- @google-cloud/tasks
- openai

---

*Last Updated: 2026-01-17*
