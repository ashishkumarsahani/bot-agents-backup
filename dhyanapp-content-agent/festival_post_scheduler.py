"""
Festival Post Scheduler for DhyanApp.

This service handles:
- Running festival posts at random times before 10 AM IST
- Integrating Calendarific, custom topics, and history
- Posting festivals in Hindi and English
- Generating general spiritual posts when no festivals
"""

import os
import uuid
import json
import random
import time
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from dotenv import load_dotenv

from llm_usage_tracker import record_openai_response, record_openai_image
from calendarific_service import get_calendarific_service
from festival_history_manager import get_festival_history_manager
from firestore_service import get_firestore_service
from image_generator_service import get_image_generator_service

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DHYANI_USER_ID = "7es9AYnaW7afNtMeOBtXl8Z2ILF3"

# General topics for days with no festivals
DAILY_SPIRITUAL_TOPICS = [
    {"name": "Morning Meditation", "description": "The importance of starting your day with meditation and mindfulness"},
    {"name": "Gratitude Practice", "description": "Cultivating gratitude in daily life for inner peace and happiness"},
    {"name": "Yoga and Wellness", "description": "The benefits of yoga for physical, mental and spiritual well-being"},
    {"name": "Inner Peace", "description": "Finding inner peace amidst the chaos of modern life"},
    {"name": "Mindful Living", "description": "Practicing mindfulness in everyday activities"},
    {"name": "Self-Love and Care", "description": "The importance of self-love and taking care of your mental health"},
    {"name": "Positive Affirmations", "description": "The power of positive thinking and affirmations"},
    {"name": "Spiritual Growth", "description": "Journey of spiritual growth and self-discovery"},
    {"name": "Karma and Good Deeds", "description": "The significance of karma and doing good in life"},
    {"name": "Nature and Spirituality", "description": "Connecting with nature for spiritual awakening"},
    {"name": "Pranayama Benefits", "description": "The healing power of breath control and pranayama"},
    {"name": "Detachment and Peace", "description": "Learning the art of detachment for mental peace"},
    {"name": "Compassion and Kindness", "description": "Spreading love, compassion and kindness in the world"},
    {"name": "Silence and Solitude", "description": "The spiritual benefits of silence and spending time alone"},
    {"name": "Daily Wisdom", "description": "Ancient wisdom for modern life challenges"},
]


class FestivalPostScheduler:
    """Scheduler for festival posts."""

    def __init__(self):
        """Initialize the festival scheduler."""
        self.calendarific = get_calendarific_service()
        self.history = get_festival_history_manager()
        self.firestore = get_firestore_service()
        self.image_service = get_image_generator_service()

    def get_topics_for_today(self) -> list[dict]:
        """
        Get all topics to post about today.

        Returns:
            List of topic dictionaries with name, description, and source
        """
        topics = []

        # 1. Check custom topics for today first (highest priority)
        custom_topics = self.history.get_custom_topics_for_date()
        for topic in custom_topics:
            if not self.history.is_already_posted(topic, "english"):
                topics.append({
                    "name": topic,
                    "description": f"Special day: {topic}",
                    "source": "custom"
                })

        # 2. Get festivals from Calendarific
        festivals = self.calendarific.get_top_festivals_for_today(2)
        for festival in festivals:
            info = self.calendarific.format_holiday_info(festival)
            if not self.history.is_already_posted(info['name'], "english"):
                topics.append({
                    "name": info['name'],
                    "description": info['description'] or f"Celebrating {info['name']}",
                    "source": "calendarific"
                })

        # 3. If no topics found, pick a random spiritual topic
        if not topics:
            # Get today's day of year to have consistent topic for the day
            day_of_year = date.today().timetuple().tm_yday
            topic_index = day_of_year % len(DAILY_SPIRITUAL_TOPICS)
            daily_topic = DAILY_SPIRITUAL_TOPICS[topic_index]

            if not self.history.is_already_posted(daily_topic['name'], "english"):
                topics.append({
                    "name": daily_topic['name'],
                    "description": daily_topic['description'],
                    "source": "daily_spiritual"
                })

        logger.info(f"Found {len(topics)} topics for today")
        return topics

    def create_festival_post(self, topic_name: str, topic_description: str, language: str, source: str = "festival") -> Optional[str]:
        """
        Create and post a festival/topic post.

        Args:
            topic_name: Name of the topic
            topic_description: Description
            language: "english" or "hindi"
            source: Source of the topic

        Returns:
            Post ID if successful
        """
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Adjust prompt based on whether it's a festival or general topic
        is_festival = source in ["calendarific", "custom"]

        # Generate content
        if language.lower() == "hindi":
            if is_festival:
                prompt = f"""आप एक आध्यात्मिक और सांस्कृतिक लेखक हैं। "{topic_name}" के बारे में एक सुंदर और प्रेरणादायक पोस्ट लिखें।

विषय जानकारी: {topic_description}

JSON प्रारूप में जवाब दें:
{{
    "content": "मुख्य पोस्ट - 100-150 शब्दों में त्योहार/दिवस का महत्व, परंपराएं और आध्यात्मिक संदेश। शुभकामनाएं भी शामिल करें।",
    "description": "छोटा विवरण (20-30 शब्द)",
    "saying": "थीम (2-4 शब्द)"
}}

शुद्ध हिंदी में लिखें। केवल JSON लौटाएं।"""
            else:
                prompt = f"""आप एक आध्यात्मिक लेखक हैं। "{topic_name}" के बारे में एक प्रेरणादायक पोस्ट लिखें।

विषय: {topic_description}

JSON प्रारूप में जवाब दें:
{{
    "content": "मुख्य पोस्ट - 100-150 शब्दों में विषय का महत्व और जीवन में इसका लाभ। प्रेरणादायक और सकारात्मक।",
    "description": "छोटा विवरण (20-30 शब्द)",
    "saying": "थीम (2-4 शब्द)"
}}

शुद्ध हिंदी में लिखें। केवल JSON लौटाएं।"""
        else:
            if is_festival:
                prompt = f"""You are a spiritual and cultural writer. Write a beautiful post about "{topic_name}".

Topic info: {topic_description}

Generate JSON:
{{
    "content": "Main post - 100-150 words about the festival/day's significance, traditions and spiritual message. Include wishes.",
    "description": "Short description (20-30 words)",
    "saying": "Theme (2-4 words)"
}}

Return ONLY JSON."""
            else:
                prompt = f"""You are a spiritual writer. Write an inspiring post about "{topic_name}".

Topic: {topic_description}

Generate JSON:
{{
    "content": "Main post - 100-150 words about the topic's importance and benefits in life. Inspirational and positive.",
    "description": "Short description (20-30 words)",
    "saying": "Theme (2-4 words)"
}}

Return ONLY JSON."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You write beautiful posts about Indian culture, spirituality and wellness."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=800
            )
            record_openai_response(response, service="festival_post.generate")

            content = response.choices[0].message.content.strip()

            # Clean JSON
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            post_data = json.loads(content)

            # Generate post ID
            post_id = str(uuid.uuid4())

            # Generate image
            logger.info(f"Generating image for {topic_name}...")
            image_url = self._generate_topic_image(topic_name, post_data.get('saying', topic_name), post_id, is_festival)

            # Push to Firestore
            doc_id = self.firestore.push_quote(
                quote=post_data['content'],
                saying=post_data.get('saying', topic_name),
                description=post_data.get('description', ''),
                created_at=datetime.now(IST),
                image_url=image_url,
                post_id=post_id
            )

            if doc_id:
                # Record in history
                self.history.record_post(topic_name, language, doc_id, source)
                logger.info(f"[SUCCESS] Posted {language} post for {topic_name}: {doc_id}")
                return doc_id

            return None

        except Exception as e:
            logger.error(f"Failed to create post: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _generate_topic_image(self, topic_name: str, saying: str, post_id: str, is_festival: bool = True) -> Optional[str]:
        """Generate image for a topic."""
        from openai import OpenAI
        import requests

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        if is_festival:
            prompt = f"""Create a beautiful, festive square image for "{topic_name}".

Style:
- Vibrant, celebratory colors
- Traditional Indian artistic elements
- NO TEXT - just visual elements
- Professional quality for social media
- No human faces
- Festive and joyful mood

Theme: {saying}

IMPORTANT: Do NOT include any text in the image."""
        else:
            prompt = f"""Create a beautiful, serene square image for "{topic_name}".

Style:
- Soft, calming colors (purples, blues, golds, greens)
- Spiritual/meditation aesthetic
- NO TEXT - just visual elements
- Elements like lotus, nature, light, peaceful scenes
- Professional quality for social media
- No human faces
- Peaceful and inspiring mood

Theme: {saying}

IMPORTANT: Do NOT include any text in the image."""

        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            record_openai_image(model="dall-e-3", service="festival_post.image", n=1)

            image_url = response.data[0].url

            # Download image
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()

            # Add text overlay
            if is_festival:
                display_text = f"Happy {topic_name}!" if len(topic_name.split()) <= 4 else topic_name
            else:
                display_text = topic_name

            final_image = self.image_service.add_text_to_image(
                img_response.content,
                display_text,
                saying
            )

            # Upload to Firebase
            firebase_url = self.image_service.upload_to_firebase(final_image, post_id)
            return firebase_url

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            return None

    def run_daily_festival_posts(self) -> list[str]:
        """
        Run the daily festival posting job.

        Returns:
            List of created post IDs
        """
        logger.info("=" * 60)
        logger.info("FESTIVAL POST BOT - DAILY RUN")
        logger.info(f"Date: {date.today()}")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        post_ids = []

        # Get topics for today
        topics = self.get_topics_for_today()

        if not topics:
            logger.info("No new topics to post today (all already posted)")
            return post_ids

        # Post each topic in both languages (limit to 2 topics max)
        for topic in topics[:2]:
            logger.info(f"\n[TOPIC] {topic['name']} (Source: {topic['source']})")

            # Post in English
            if not self.history.is_already_posted(topic['name'], "english"):
                eng_id = self.create_festival_post(
                    topic['name'],
                    topic['description'],
                    "english",
                    topic['source']
                )
                if eng_id:
                    post_ids.append(eng_id)

            # Post in Hindi
            if not self.history.is_already_posted(topic['name'], "hindi"):
                hindi_id = self.create_festival_post(
                    topic['name'],
                    topic['description'],
                    "hindi",
                    topic['source']
                )
                if hindi_id:
                    post_ids.append(hindi_id)

        logger.info("=" * 60)
        logger.info(f"COMPLETED: Created {len(post_ids)} posts")
        logger.info("=" * 60)

        return post_ids


def run_festival_posts_with_random_delay():
    """
    Run festival posts with a random delay (for posting at random time before 10 AM IST).
    This should be called early morning (e.g., 5 AM IST).
    """
    # Calculate random delay (0 to 5 hours = 0 to 18000 seconds)
    # This means if run at 5 AM, posts will happen between 5 AM and 10 AM
    max_delay_seconds = 5 * 60 * 60  # 5 hours
    random_delay = random.randint(0, max_delay_seconds)

    delay_hours = random_delay // 3600
    delay_minutes = (random_delay % 3600) // 60

    expected_time = datetime.now(IST) + timedelta(seconds=random_delay)

    logger.info(f"Random delay: {delay_hours}h {delay_minutes}m")
    logger.info(f"Expected post time: {expected_time.strftime('%H:%M:%S IST')}")

    # Sleep for random duration
    time.sleep(random_delay)

    # Now run the posts
    scheduler = FestivalPostScheduler()
    return scheduler.run_daily_festival_posts()


def run_festival_posts():
    """Main function to run festival posts immediately."""
    scheduler = FestivalPostScheduler()
    return scheduler.run_daily_festival_posts()


# Singleton instance
_festival_scheduler = None


def get_festival_scheduler() -> FestivalPostScheduler:
    """Get the singleton instance of the festival scheduler."""
    global _festival_scheduler
    if _festival_scheduler is None:
        _festival_scheduler = FestivalPostScheduler()
    return _festival_scheduler


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Festival Post Scheduler")
    parser.add_argument("--run-now", action="store_true", help="Run festival posts immediately")
    parser.add_argument("--run-random", action="store_true", help="Run with random delay (for cron)")
    parser.add_argument("--add-topic", type=str, help="Add a custom topic for today")
    parser.add_argument("--add-topic-date", type=str, help="Date for custom topic (YYYY-MM-DD)")
    parser.add_argument("--show-history", action="store_true", help="Show posting history")
    parser.add_argument("--show-topics", action="store_true", help="Show today's topics")

    args = parser.parse_args()

    scheduler = get_festival_scheduler()

    if args.add_topic:
        target_date = None
        if args.add_topic_date:
            target_date = datetime.strptime(args.add_topic_date, "%Y-%m-%d").date()
        else:
            target_date = date.today()
        scheduler.history.add_custom_topic(args.add_topic, target_date)
        print(f"Added topic: {args.add_topic} for {target_date}")

    elif args.show_history:
        scheduler.history.display_all_records()

    elif args.show_topics:
        topics = scheduler.get_topics_for_today()
        print(f"\nTopics for today ({len(topics)}):")
        for t in topics:
            print(f"  - {t['name']} ({t['source']})")
            print(f"    {t['description']}")

    elif args.run_random:
        logger.info("Running with random delay...")
        post_ids = run_festival_posts_with_random_delay()
        print(f"\nCreated {len(post_ids)} posts")

    elif args.run_now:
        post_ids = scheduler.run_daily_festival_posts()
        print(f"\nCreated {len(post_ids)} posts")

    else:
        parser.print_help()
