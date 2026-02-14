# Post Creation Workflow

## Overview

Two types of content are generated daily by bot personas:
- **Quotes** (6:00 AM IST) - Authentic quotes from spiritual teachers with persona commentary
- **Content Posts** (6:00 PM IST) - Original spiritual/wellness content with generated images

Both follow the same high-level flow: rotate bot -> generate content -> create image -> publish to Firestore.

## Schedule

| Time (IST) | UTC | Script | Generator |
|------------|-----|--------|-----------|
| 6:00 AM | 00:30 UTC | `run_persona_quotes.sh` | `persona_quote_generator.py` |
| 6:00 PM | 12:30 UTC | `run_persona_posts.sh` | `persona_post_generator.py` |

Crontab entries:
```cron
30 0 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_quotes.sh
30 12 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_posts.sh
```

Both scripts run with `--run-now --single --no-engagement` flags:
- `--run-now`: Execute immediately (don't wait for schedule)
- `--single`: Generate one post only (not all today's posters)
- `--no-engagement`: Skip local engagement (Cloud Functions handle it)

## Bot Rotation

Bots are selected via round-robin rotation. Each generator maintains its own state file.

**State files:**
- Posts: `rotation_state.json` - tracks `poster_index` (0-7)
- Quotes: `quote_rotation_state.json` - tracks `poster_index` (0-7)

**Rotation logic:**
```
1. Load state file -> get current poster_index
2. Select accounts[poster_index] as today's poster
3. Increment poster_index (wraps at 8 -> 0)
4. Save updated state with today's date
```

With 8 bots and 1 post/day each type, every bot posts once every 8 days.

**Example state (`rotation_state.json`):**
```json
{
  "last_date": "2026-02-14",
  "poster_index": 6,
  "commenter_index": 2
}
```

## Content Post Generation Flow

```
┌─────────────────────────────────────────────────────┐
│                 persona_post_generator.py            │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  1. Rotate Bot   │
                  │  (round-robin)   │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐     ┌──────────────────┐
                  │  2. Festival     │────►│  Festival found? │
                  │     Check        │     │  Generate themed │
                  └────────┬─────────┘     │  post instead    │
                           │ No            └──────────┬───────┘
                           ▼                          │
                  ┌──────────────────┐                │
                  │  3. Web Search   │                │
                  │  (SerperDev API) │                │
                  └────────┬─────────┘                │
                           │                          │
                           ▼                          │
                  ┌──────────────────┐                │
                  │  4. Generate     │◄───────────────┘
                  │  Content (GPT)   │
                  │  - Post text     │
                  │  - Brief saying  │
                  │  - Description   │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  5. Generate     │
                  │  Image           │
                  │  (dhyanapp API)  │
                  │  + text overlay  │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  6. Upload to    │
                  │  Firebase Storage│
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  7. Create Post  │
                  │  in Firestore    │
                  │  posts/{postId}  │
                  └──────────────────┘
                           │
                           │ Triggers onPostCreated
                           ▼
                  Cloud Functions handle
                  engagement (see liking
                  and commenting docs)
```

### Step Details

#### 1. Bot Rotation
- Reads `rotation_state.json`
- Selects next bot by `poster_index`
- Increments and saves index

#### 2. Festival Check
- Queries `Festivals/{current_year}/festivals` in Firestore
- Matches today's date (format: "Month Day", e.g. "February 14")
- If found: generates festival-specific content with the festival's story, significance, and rituals
- Festival data includes Hindi and English versions

#### 3. Web Search
- Generates search queries based on bot's persona and topics
- Calls SerperDev API with the queries
- Collects relevant content snippets for context

#### 4. Content Generation
- Uses GPT-4o-mini with the bot's persona as system prompt
- Inputs: web search results, persona details, topics, scriptures
- Outputs:
  - `content`: Main post text (100-200+ words)
  - `brief_saying`: Short quote (2-5 words)
  - `description`: Subtitle (15-25 words)

#### 5. Image Generation
- Randomly selects from 15+ artistic styles:
  - Traditional Indian Miniature, Tanjore Painting, Madhubani Folk Art
  - Watercolor Spiritual, Mystical Ethereal, Warli Art
  - Temple Architecture, Lotus Garden, Sacred Geometry
  - Studio Ghibli, Oil Painting, Anime, Gothic Noir, etc.
- Sends style prompt to dhyanapp-services API
- Adds text overlay with the brief saying and bot attribution

#### 6-7. Upload and Publish
- Uploads image to Firebase Storage
- Creates post document in `posts/{postId}` with fields:
  - `content`, `description`, `imageUrl`, `createdBy`, `creatorName`
  - `createdAt` (milliseconds), `_botGenerated: true`, `_language`

## Quote Generation Flow

Similar to content posts with these differences:

- Uses `quote_rotation_state.json` for separate rotation
- Searches specifically for authentic quotes from the bot's followed teachers/scriptures
- Falls back to AI-generated quotes if web search doesn't find good results
- Uses language-specific fonts for text overlay:
  - **Hindi**: Noto Serif Devanagari, Noto Sans Devanagari
  - **English**: Samarkan (decorative), Cinzel (classical), Great Vibes (script), Playfair Display, Cormorant Garamond, Philosopher
- Includes persona commentary alongside the quote

## Post Document Structure

```javascript
// Firestore: posts/{postId}
{
  content: "Main post text...",
  description: "Brief subtitle...",
  imageUrl: "https://storage.googleapis.com/...",
  createdBy: "7es9AYnaW7afNtMeOBtXl8Z2ILF3",  // bot user ID
  creatorName: "Dhyani",
  createdAt: 1739523000000,  // milliseconds since epoch
  likeCount: 0,              // incremented by engagement
  commentCount: 0,           // incremented by engagement
  viewCount: 0,              // incremented by engagement
  _botGenerated: true,
  _language: "hindi"         // or "english"
}
```

## CLI Reference

```bash
# Production (used by cron)
python persona_post_generator.py --run-now --single --no-engagement

# Test specific account
python persona_post_generator.py --test-account dhyani --test-mode

# Check rotation
python persona_post_generator.py --show-rotation

# Festival testing
python persona_post_generator.py --check-festival
python persona_post_generator.py --test-festival "Holi" --test-mode

# Quote generation
python persona_quote_generator.py --run-now --single --no-engagement
python persona_quote_generator.py --test-account yogini --test-mode
python persona_quote_generator.py --show-rotation
```
