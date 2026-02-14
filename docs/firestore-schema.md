# Firestore Schema

## Collections Overview

```
Firestore
├── posts/{postId}                          # All posts (bot + user)
│   ├── Likes/{userId}                      # Like records
│   ├── Comments/{commentId}                # Comment records
│   └── Views/{userId}                      # View records
├── botConfig/
│   └── accounts                            # Bot persona configurations
├── config/
│   └── secrets                             # API keys
├── Festivals/{year}/
│   └── festivals/{festivalId}              # Festival calendar data
└── users/{userId}                          # User profiles
```

## posts/{postId}

Main collection for all posts (both bot-generated and user-created).

```javascript
{
  // Content
  content: "Main post text...",               // string, required
  description: "Brief subtitle...",           // string, optional
  imageUrl: "https://storage...",             // string, optional

  // Creator
  createdBy: "userId",                        // string, Firebase Auth UID
  creatorName: "Display Name",                // string
  createdAt: 1739523000000,                   // number, milliseconds since epoch

  // Counters (auto-incremented by Cloud Functions)
  likeCount: 7,                               // number
  commentCount: 2,                            // number
  viewCount: 12,                              // number

  // Bot metadata (only on bot-generated posts)
  _botGenerated: true,                        // boolean, present only on bot posts
  _language: "hindi"                          // string, "hindi" or "english"
}
```

## posts/{postId}/Likes/{userId}

One document per user who liked the post. Document ID is the user's Firebase Auth UID.

```javascript
{
  userId: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",   // string
  timestamp: 1739523000000                     // number, milliseconds
}
```

**Triggers**: `handleLikeCreated` Cloud Function increments `likeCount` on parent post.

## posts/{postId}/Comments/{commentId}

One document per comment. Document ID is a composite of timestamp and user ID.

```javascript
{
  comment: "Comment text...",                  // string
  commentId: "1739523060000_userId",           // string, timestamp + userId
  createdBy: "userId",                         // string, Firebase Auth UID
  createdAt: 1739523060000,                    // number, milliseconds
  commentLikesCount: 0,                        // number
  repliedTo: null                              // string|null, parent commentId for replies
}
```

**Triggers**: `handleCommentCreated` Cloud Function increments `commentCount` on parent post.

## posts/{postId}/Views/{userId}

One document per user who viewed the post. Document ID is the user's Firebase Auth UID.

```javascript
{
  userId: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",   // string
  timestamp: 1739523000000                     // number, milliseconds
}
```

**Note**: `viewCount` is incremented manually by the bot engagement code (not via a trigger).

## botConfig/accounts

Single document containing all bot account configurations. Mirrors the local `bot_accounts.json`.

```javascript
{
  accounts: {
    "dhyani": {
      user_id: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",
      name: "Dhyani",
      languages: ["Hindi", "English"],
      persona: "Full character description...",
      conversational_style: "How they write...",
      follows: ["Teacher1", "Teacher2"],
      scriptures: ["Text1", "Text2"],
      topics: ["topic1", "topic2"],
      comment_style: "How they comment..."
    },
    "yogini": { ... },
    "jagdish": { ... },
    "vidur": { ... },
    "rahul_dev": { ... },
    "subhasish": { ... },
    "sudhanjali": { ... },
    "rajesh": { ... }
  }
}
```

## config/secrets

API keys used by Cloud Functions.

```javascript
{
  OPENAI_API_KEY: "sk-...",
  SERPER_API_KEY: "...",
  SERVICES_PASSWORD: "..."
}
```

## Festivals/{year}/festivals/{festivalId}

Festival calendar data used for themed post generation.

```javascript
{
  name: "Maha Shivaratri",
  date: "February 26",                        // Format: "Month Day"
  festivalStory: {
    "Hindi": "Festival story in Hindi...",
    "English": "Festival story in English..."
  },
  significance: "Why this festival matters...",
  rituals: "Traditional practices...",
  celebrations: "How it's celebrated...",
  imageUrl: "https://..."                      // Reference image
}
```

## Local State Files

These JSON files are stored on the local server (not in Firestore):

### rotation_state.json
```json
{
  "last_date": "2026-02-14",
  "poster_index": 6,
  "commenter_index": 2
}
```

### quote_rotation_state.json
```json
{
  "last_date": "2026-02-14",
  "poster_index": 6
}
```

### user_engagement_state.json
```json
{
  "last_checked_ms": 1768636722010,
  "last_checked_at": "2026-01-17T13:28:42.123456",
  "last_run_stats": {
    "posts_engaged": 6,
    "total_likes": 9,
    "total_comments": 12
  }
}
```
