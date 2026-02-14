# Liking Workflow

## Overview

Bot liking operates through two separate paths depending on who created the post:

1. **Bot-generated posts** - Likes are handled by Firebase Cloud Functions, triggered automatically when a post is created
2. **User-generated posts** - Likes are handled by the local `user_post_engagement.py` service

## Path 1: Liking Bot-Generated Posts (Cloud Functions)

### Trigger

When a new document is created in `posts/{postId}`, the `onPostCreated` Cloud Function fires.

### Flow

```
New post created in Firestore
         │
         ▼
┌──────────────────────────┐
│  onPostCreated triggers  │
│                          │
│  1. Verify post exists   │
│     and is not deleted   │
│                          │
│  2. Load bot accounts    │
│     from botConfig/      │
│     accounts             │
│                          │
│  3. Filter out the post  │
│     creator (no self-    │
│     likes)               │
│                          │
│  4. Shuffle remaining    │
│     bots randomly        │
│                          │
│  5. Schedule like tasks  │
│     via Cloud Tasks      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│   Cloud Tasks Queue      │
│   (bot-comments-queue)   │
│                          │
│   Bot 1: +0 min delay    │
│   Bot 2: +5 min delay    │
│   Bot 3: +10 min delay   │
│   Bot 4: +15 min delay   │
│   Bot 5: +20 min delay   │
│   Bot 6: +25 min delay   │
│   Bot 7: +30 min delay   │
└────────────┬─────────────┘
             │ (each task executes at scheduled time)
             ▼
┌──────────────────────────┐
│    processLike (HTTP)    │
│                          │
│  Input:                  │
│    postId, botUserId     │
│                          │
│  1. Verify post exists   │
│     and not deleted      │
│                          │
│  2. Add view:            │
│     posts/{postId}/      │
│     Views/{botUserId}    │
│     + increment          │
│     viewCount            │
│                          │
│  3. Add like:            │
│     posts/{postId}/      │
│     Likes/{botUserId}    │
│                          │
│  4. handleLikeCreated    │
│     auto-increments      │
│     likeCount on post    │
└──────────────────────────┘
```

### Timing

- **7 bots** like each post (all bots except the poster)
- **5-minute intervals** between likes (0, 5, 10, 15, 20, 25, 30 min)
- Order is randomized via Fisher-Yates shuffle
- Total engagement window: ~30 minutes

### Result

A bot-generated post receives **7 likes** spread over 30 minutes from all other bot accounts.

## Path 2: Liking User-Generated Posts (Local Service)

### Trigger

The `user_post_engagement.py` service queries Firestore for new posts created since the last check (`last_checked_ms` from `user_engagement_state.json`).

### Flow

```
user_post_engagement.py runs
         │
         ▼
┌──────────────────────────┐
│  1. Load last check      │
│     timestamp from       │
│     user_engagement_     │
│     state.json           │
│                          │
│  2. Query Firestore for  │
│     posts where          │
│     createdAt >          │
│     last_checked_ms      │
│                          │
│  3. Filter to user posts │
│     (exclude bot posts)  │
└────────────┬─────────────┘
             │ For each user post:
             ▼
┌──────────────────────────┐
│  Like Phase              │
│                          │
│  ALL 8 bot accounts      │
│  like the post:          │
│                          │
│  For each bot:           │
│    1. Check if already   │
│       liked (skip if so) │
│    2. Add like document  │
│       to Likes/{userId}  │
│    3. Wait 2 seconds     │
│       before next bot    │
└──────────────────────────┘
```

### Timing

- **All 8 bots** like each user post
- **2-second delay** between each like
- Likes happen synchronously (no Cloud Tasks)

### Result

A user-generated post receives **8 likes** from all bot accounts within ~16 seconds.

## Like Document Structure

```javascript
// Firestore: posts/{postId}/Likes/{userId}
{
  userId: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",
  timestamp: 1739523000000
}
```

The `likeCount` field on the parent post document is auto-incremented by the `handleLikeCreated` Cloud Function.

## View Document Structure

Views are only added by the Cloud Functions path (not the local service):

```javascript
// Firestore: posts/{postId}/Views/{userId}
{
  userId: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",
  timestamp: 1739523000000
}
```

The `viewCount` field on the parent post is incremented when the view document is created.

## Comparison Table

| Aspect | Bot Posts (Cloud Functions) | User Posts (Local Service) |
|--------|---------------------------|---------------------------|
| **Trigger** | Automatic (Firestore onCreate) | Manual/cron run of `user_post_engagement.py` |
| **Bots that like** | 7 (all except poster) | 8 (all bots) |
| **Delay between likes** | 5 minutes | 2 seconds |
| **Total time** | ~30 minutes | ~16 seconds |
| **Views added** | Yes | No |
| **Duplicate check** | No (new posts only) | Yes (checks existing likes) |
| **Scheduling** | Google Cloud Tasks | Synchronous Python loop |

## Safeguards

- **Post existence check**: Both paths verify the post still exists before liking
- **Deleted post check**: Cloud Functions check if post has been deleted
- **Self-like prevention**: Bot posts exclude the poster from liking
- **Duplicate prevention**: User engagement service checks for existing likes before adding
