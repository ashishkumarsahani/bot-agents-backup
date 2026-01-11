# DhyanApp Content Agent

Automated content generation and engagement system for DhyanApp using AI-powered bot personas.

## Overview

This service manages multiple bot personas that create spiritual/wellness content, post quotes, and engage with each other's posts to build community activity.

## Components

### 1. Persona Post Generator (`persona_post_generator.py`)

Generates spiritual/wellness posts based on each persona's unique style and interests.

**Features:**
- Web search for relevant content using SerperDev API
- AI-powered content generation with GPT-4o-mini
- Multiple image styles (Traditional Indian Miniature, Tanjore, Madhubani, etc.)
- Festival detection - automatically generates festival-specific posts
- Automatic engagement from other bot accounts

**CLI Options:**
```bash
python persona_post_generator.py --run-now              # Run for all today's posters
python persona_post_generator.py --run-now --single     # Run for one poster only
python persona_post_generator.py --test-account dhyani  # Test specific account
python persona_post_generator.py --show-rotation        # Show today's rotation
python persona_post_generator.py --check-festival       # Check if today is a festival
python persona_post_generator.py --test-festival "Holi" # Test festival post
python persona_post_generator.py --no-engagement        # Skip engagement
python persona_post_generator.py --test-mode            # Use short delays (10-30s)
```

### 2. Persona Quote Generator (`persona_quote_generator.py`)

Searches for and posts authentic quotes from saints, scriptures, and spiritual teachers.

**Features:**
- Web search for authentic quotes (with AI fallback)
- Quote text overlay on generated images
- Language-specific fonts (Devanagari for Hindi, decorative fonts for English)
- Persona commentary on each quote
- Automatic engagement from other bot accounts

**Available Fonts:**
- Hindi: Noto Serif/Sans Devanagari
- English: Samarkan, Cinzel, Great Vibes, Playfair Display, Cormorant Garamond, Philosopher

**CLI Options:**
```bash
python persona_quote_generator.py --run-now              # Run for all today's posters
python persona_quote_generator.py --run-now --single     # Run for one poster only
python persona_quote_generator.py --test-account yogini  # Test specific account
python persona_quote_generator.py --show-rotation        # Show today's rotation
python persona_quote_generator.py --no-engagement        # Skip engagement
python persona_quote_generator.py --test-mode            # Use short delays
```

### 3. Engagement Service (`engagement_service.py`)

Handles automated likes and comments from bot accounts on posts.

**Features:**
- Configurable delay between engagements (5-10 minutes default)
- Two rounds of comments for natural conversation flow
- Anecdote sharing by select personas
- Reply threads between bots
- Test mode with shorter delays

## Bot Accounts

Configured in `bot_accounts.json`. Each account has:
- `name` - Display name
- `user_id` - Firebase user ID
- `persona` - Character description
- `conversational_style` - Writing style (Hindi/English)
- `follows` - Saints/teachers they follow
- `scriptures` - Sacred texts they reference
- `topics` - Areas of interest
- `comment_style` - How they comment on posts

## Schedule

Managed via cron jobs:

| Time (IST) | Task | Description |
|------------|------|-------------|
| 6:00 AM | Quote | One quote post with engagement |
| 6:00 PM | Post | One regular post with engagement |

**Crontab entries:**
```cron
# 6 AM IST (0:30 UTC) - Single quote with engagement
30 0 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_quotes.sh

# 6 PM IST (12:30 UTC) - Single post with engagement
30 12 * * * /home/admin/bot_agents/dhyanapp-content-agent/run_persona_posts.sh
```

## Configuration

### Environment Variables

Create a `.env` file or set these variables:
- `SERPER_API_KEY` - SerperDev API key for web search
- `OPENAI_API_KEY` - OpenAI API key for GPT-4o-mini
- `FIREBASE_CREDENTIALS_PATH` - Path to Firebase service account JSON

### Firebase Collections

- `Posts` - All posts created by bots
- `Festivals/{year}/festivals` - Festival data with dates and stories
- `servicePasswords/image_generation` - Password for image API

## Directory Structure

```
dhyanapp-content-agent/
├── persona_post_generator.py    # Main post generator
├── persona_quote_generator.py   # Quote generator with image overlay
├── engagement_service.py        # Likes and comments automation
├── bot_accounts.json            # Bot persona configurations
├── rotation_state.json          # Post rotation tracking
├── quote_rotation_state.json    # Quote rotation tracking
├── firebase_credentials.json    # Firebase service account
├── fonts/                       # Custom fonts for quote images
│   ├── Samarkan.ttf
│   ├── Cinzel-Bold.ttf
│   ├── GreatVibes-Regular.ttf
│   ├── PlayfairDisplay-Bold.ttf
│   ├── CormorantGaramond-Bold.ttf
│   └── Philosopher-Bold.ttf
├── run_persona_posts.sh         # Cron script for posts
├── run_persona_quotes.sh        # Cron script for quotes
├── post_cron.log                # Post generation logs
└── quote_cron.log               # Quote generation logs
```

## Image Styles

Posts can use various artistic styles:
- Traditional Indian Miniature
- Tanjore Painting Style
- Watercolor Spiritual
- Madhubani Folk Art
- Mystical Ethereal
- Warli Art Style
- Temple Architecture
- Lotus Garden Serene
- Studio Ghibli Style
- Oil Painting
- Anime Style
- Gothic Noir
- And more...

## Testing

```bash
# Activate virtual environment
source .venv/bin/activate

# Test single post with short delays
python persona_post_generator.py --test-account dhyani --test-mode

# Test quote generation
python persona_quote_generator.py --test-account yogini --test-mode

# Test festival post
python persona_post_generator.py --test-festival "Maha Shivaratri" --test-mode

# Check today's rotation
python persona_post_generator.py --show-rotation
python persona_quote_generator.py --show-rotation
```

## Logs

- `post_cron.log` - Daily post generation logs
- `quote_cron.log` - Daily quote generation logs

View recent activity:
```bash
tail -100 post_cron.log
tail -100 quote_cron.log
```

## Dependencies

- Python 3.11+
- openai - GPT-4o-mini for content generation
- firebase-admin - Firestore and Storage
- Pillow - Image text overlay
- requests - API calls
- python-dotenv - Environment configuration

Install:
```bash
python -m venv .venv
source .venv/bin/activate
pip install openai firebase-admin Pillow requests python-dotenv
```
