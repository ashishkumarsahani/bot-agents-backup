"""
User Post Engagement Service for DhyanApp.

This service handles:
- Checking for new posts by real users since last checked time
- Having all bots like new user posts
- Having 2 random bots comment thoughtfully on each post
- Analyzing post text and images for contextual comments
"""

import os
import io
import json
import random
import logging
import time
import base64
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, List

from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, storage

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = Path(__file__).parent / "user_engagement_state.json"

from bot_personas_store import get_all_personas

FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
)
FIREBASE_STORAGE_BUCKET = "dhyanapp-90de4.appspot.com"


class UserPostEngagementService:
    """Service for engaging with posts created by real users."""

    def __init__(self):
        """Initialize the user post engagement service."""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.accounts = self._load_accounts()
        self.bot_user_ids = self._get_bot_user_ids()
        self._initialize_firebase()

    def _initialize_firebase(self):
        """Initialize Firebase."""
        try:
            if not firebase_admin._apps:
                if os.path.exists(FIREBASE_CREDENTIALS_PATH):
                    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                    firebase_admin.initialize_app(cred, {
                        'storageBucket': FIREBASE_STORAGE_BUCKET
                    })
            self.db = firestore.client()
            self.bucket = storage.bucket(FIREBASE_STORAGE_BUCKET)
            logger.info("[SUCCESS] Firebase initialized for user engagement")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize Firebase: {e}")
            self.db = None
            self.bucket = None

    def _load_accounts(self) -> dict:
        """Load bot accounts from MongoDB."""
        try:
            return get_all_personas()
        except Exception as e:
            logger.error(f"[ERROR] Failed to load bot accounts: {e}")
            return {}

    def _get_bot_user_ids(self) -> set:
        """Get set of all bot user IDs."""
        return {account['user_id'] for account in self.accounts.values()}

    def _load_state(self) -> dict:
        """Load engagement state from file."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[ERROR] Failed to load state: {e}")
        return {"last_checked_ms": 0}

    def _save_state(self, state: dict):
        """Save engagement state to file."""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"[ERROR] Failed to save state: {e}")

    def get_new_user_posts(self, since_ms: int) -> List[dict]:
        """
        Get posts created by real users since the given timestamp.

        Args:
            since_ms: Timestamp in milliseconds to check from

        Returns:
            List of post dictionaries
        """
        try:
            posts_ref = self.db.collection('posts')

            # Query for posts created after the timestamp
            query = posts_ref.where('createdAt', '>', since_ms).order_by('createdAt')

            user_posts = []
            for doc in query.stream():
                post_data = doc.to_dict()
                post_data['id'] = doc.id

                # Skip bot-generated posts
                if post_data.get('_botGenerated', False):
                    continue

                # Skip posts by bot accounts
                if post_data.get('createdBy') in self.bot_user_ids:
                    continue

                # Skip deleted posts
                if post_data.get('deleted', False):
                    continue

                user_posts.append(post_data)

            logger.info(f"Found {len(user_posts)} new user posts since {since_ms}")
            return user_posts

        except Exception as e:
            logger.error(f"[ERROR] Failed to query new posts: {e}")
            return []

    def download_image(self, image_url: str) -> Optional[bytes]:
        """Download image from URL."""
        try:
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            logger.warning(f"Failed to download image: {e}")
            return None

    def analyze_post_with_vision(self, post_content: str, image_url: Optional[str] = None) -> str:
        """
        Analyze post content and image using GPT-4 Vision.

        Args:
            post_content: Text content of the post
            image_url: Optional URL of the post image

        Returns:
            Analysis summary for comment generation
        """
        messages = [
            {
                "role": "system",
                "content": "You analyze spiritual/meditation app posts. Summarize the key themes, emotions, and spiritual topics in 2-3 sentences. Focus on what would be meaningful to comment on."
            }
        ]

        content = []
        content.append({
            "type": "text",
            "text": f"Analyze this post:\n\n{post_content[:1000]}"
        })

        # Add image if available
        if image_url:
            try:
                image_bytes = self.download_image(image_url)
                if image_bytes:
                    base64_image = base64.b64encode(image_bytes).decode('utf-8')
                    # Determine image type
                    if image_url.lower().endswith('.png'):
                        media_type = "image/png"
                    else:
                        media_type = "image/jpeg"

                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{base64_image}",
                            "detail": "low"
                        }
                    })
                    logger.info("Added image to analysis")
            except Exception as e:
                logger.warning(f"Failed to process image for analysis: {e}")

        messages.append({"role": "user", "content": content})

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=200,
                temperature=0.5
            )
            analysis = response.choices[0].message.content.strip()
            logger.info(f"Post analysis: {analysis[:100]}...")
            return analysis
        except Exception as e:
            logger.error(f"[ERROR] Failed to analyze post: {e}")
            return post_content[:200]

    def get_existing_comments(self, post_id: str) -> List[dict]:
        """
        Get existing comments on a post.

        Args:
            post_id: The post document ID

        Returns:
            List of comment dictionaries with commenter info
        """
        try:
            comments_ref = self.db.collection('posts').document(post_id).collection('Comments')
            comments = comments_ref.order_by('createdAt').stream()

            result = []
            for c in comments:
                comment_data = c.to_dict()
                # Get commenter name
                commenter_id = comment_data.get('createdBy', '')
                commenter_name = self._get_user_name(commenter_id)
                comment_data['commenter_name'] = commenter_name
                result.append(comment_data)

            return result
        except Exception as e:
            logger.error(f"[ERROR] Failed to get comments: {e}")
            return []

    def _get_user_name(self, user_id: str) -> str:
        """Get display name for a user ID."""
        # First check if it's a bot account
        for account in self.accounts.values():
            if account.get('user_id') == user_id:
                return account.get('name', 'User')

        # Try to get from Firestore users collection
        try:
            user_doc = self.db.collection('users').document(user_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                return user_data.get('name', user_data.get('displayName', 'User'))
        except Exception:
            pass

        return 'User'

    def generate_thoughtful_comment(self, account: dict, post_content: str,
                                     post_analysis: str, creator_name: str,
                                     existing_comments: List[dict] = None,
                                     post_language: str = 'english',
                                     next_commenter_name: str = None) -> str:
        """
        Generate a thoughtful comment based on the account's persona.

        Args:
            account: Bot account dictionary
            post_content: Original post content
            post_analysis: AI analysis of post themes
            creator_name: Name of the post creator
            existing_comments: List of existing comments on the post
            post_language: Language of the post

        Returns:
            Generated comment text
        """
        # Always match the post language — detect Hindi script in content
        is_hindi = any(0x0900 <= ord(c) <= 0x097F for c in post_content[:200])
        comment_lang = "Hindi" if (is_hindi or post_language == 'hindi') else "English"

        # Build existing comments context
        comments_context = ""
        people_to_tag = [creator_name]

        if existing_comments:
            comments_context = "\n\nExisting comments on this post:\n"
            for c in existing_comments[-5:]:  # Last 5 comments for context
                commenter = c.get('commenter_name', 'User')
                comment_text = c.get('comment', '')[:100]
                comments_context += f"- @{commenter}: {comment_text}\n"
                if commenter != account.get('name') and commenter not in people_to_tag:
                    people_to_tag.append(commenter)

        # Tag suggestion
        tag_suggestion = ""
        if len(people_to_tag) > 1 and random.random() < 0.5:
            tag_target = random.choice(people_to_tag)
            tag_suggestion = f"\nYou may naturally tag @{tag_target} if responding to their point."

        prompt = f"""You are {account['name']}, a genuine spiritual seeker and mentor on Dhyanapp.

Your persona: {account.get('persona', '')}
Your style: {account.get('conversational_style', '')}
Teachers you follow: {', '.join(account.get('follows', [])[:4])}

Post by @{creator_name} (this is your PRIMARY context — respond to what they wrote):
"{post_content[:500]}"

Post themes (supplementary context): {post_analysis}
{comments_context}
Write a thoughtful, genuine comment (20-50 words) in {comment_lang}:
- You MUST address the post creator as @{creator_name} ji in your comment{f" and tag @{next_commenter_name} ji to bring them into the conversation" if next_commenter_name else ""}
- Respond to what @{creator_name} actually shared — not generic praise
- Share insights from your own spiritual journey and tradition
- Be warm and natural, like a fellow seeker on the same path
- Sometimes be a gentle mentor, sometimes a curious fellow traveler
- Reference your tradition's wisdom only when it flows naturally
- If there are existing comments, build on the conversation

Your voice: {account.get('comment_style', '')}

AVOID:
- Generic responses ("beautiful post!", "so true!", "amazing!")
- Preaching or lecturing
- Ignoring the actual content of the post
- Repeating what others have already said

Return ONLY the comment text."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, a genuine spiritual seeker and mentor. You engage naturally and thoughtfully, sharing from your own journey."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.85,
                max_tokens=200
            )
            comment = response.choices[0].message.content.strip()
            comment = comment.strip('"\'')
            return comment
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate comment: {e}")
            return "🙏 Beautiful sharing!"

    def add_like(self, post_id: str, user_id: str) -> bool:
        """Add a like to a post."""
        try:
            timestamp = int(datetime.now(IST).timestamp() * 1000)

            # Check if already liked
            like_ref = self.db.collection('posts').document(post_id).collection('Likes').document(user_id)
            if like_ref.get().exists:
                logger.info(f"Already liked by {user_id}")
                return False

            like_ref.set({
                'userId': user_id,
                'timestamp': timestamp
            })
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to add like: {e}")
            return False

    def add_comment(self, post_id: str, user_id: str, comment_text: str) -> Optional[str]:
        """Add a comment to a post."""
        try:
            timestamp = int(datetime.now(IST).timestamp() * 1000)
            comment_id = f"{timestamp}{user_id}"

            comment_ref = self.db.collection('posts').document(post_id).collection('Comments').document(comment_id)
            comment_ref.set({
                'commentId': comment_id,
                'comment': comment_text,
                'createdBy': user_id,
                'createdAt': timestamp,
                'repliedTo': None
            })
            return comment_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to add comment: {e}")
            return None

    def engage_with_post(self, post: dict, delay_between_actions: float = 2.0) -> dict:
        """
        Engage with a single user post.

        Args:
            post: Post dictionary with id, content, imageUrl, creatorName, etc.
            delay_between_actions: Seconds to wait between actions

        Returns:
            Stats dictionary with likes and comments count
        """
        post_id = post['id']
        post_content = post.get('content', '')
        image_url = post.get('imageUrl')
        creator_name = post.get('creatorName', 'User')

        logger.info(f"\n{'='*60}")
        logger.info(f"ENGAGING WITH USER POST: {post_id}")
        logger.info(f"Creator: {creator_name}")
        logger.info(f"Content preview: {post_content[:100]}...")
        logger.info(f"{'='*60}")

        stats = {"likes": 0, "comments": 0}

        # Analyze post content and image
        post_analysis = self.analyze_post_with_vision(post_content, image_url)

        # Step 1: All bots like the post
        logger.info("\nAdding likes from all bots...")
        all_accounts = list(self.accounts.values())

        for account in all_accounts:
            if self.add_like(post_id, account['user_id']):
                stats["likes"] += 1
                logger.info(f"  ✓ Like added by {account['name']}")
            time.sleep(delay_between_actions)

        # Step 2: Select 2 random bots to comment
        commenting_accounts = random.sample(all_accounts, min(2, len(all_accounts)))
        logger.info(f"\nCommenters: {[a['name'] for a in commenting_accounts]}")

        for idx, account in enumerate(commenting_accounts):
            # Fetch existing comments (including any just added by other bots)
            existing_comments = self.get_existing_comments(post_id)
            if existing_comments:
                logger.info(f"  Found {len(existing_comments)} existing comments for context")

            # Determine the next commenter to tag
            next_commenter_name = None
            if idx + 1 < len(commenting_accounts):
                next_commenter_name = commenting_accounts[idx + 1].get('name')

            comment = self.generate_thoughtful_comment(
                account,
                post_content,
                post_analysis,
                creator_name,
                existing_comments=existing_comments,
                next_commenter_name=next_commenter_name
            )

            if self.add_comment(post_id, account['user_id'], comment):
                stats["comments"] += 1
                logger.info(f"  ✓ Comment by {account['name']}: {comment[:60]}...")

            time.sleep(delay_between_actions * 2)  # Slightly longer delay between comments

        logger.info(f"\nEngagement complete: {stats['likes']} likes, {stats['comments']} comments")
        return stats

    def run_engagement_check(self, delay_between_posts: float = 5.0) -> dict:
        """
        Main function to check for new user posts and engage with them.

        Args:
            delay_between_posts: Seconds to wait between engaging with different posts

        Returns:
            Overall stats
        """
        logger.info("=" * 60)
        logger.info("USER POST ENGAGEMENT CHECK")
        logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info("=" * 60)

        # Load state
        state = self._load_state()
        last_checked_ms = state.get('last_checked_ms', 0)

        # If first run, start from 24 hours ago to avoid flooding
        if last_checked_ms == 0:
            last_checked_ms = int((datetime.now(IST).timestamp() - 86400) * 1000)
            logger.info("First run - checking posts from last 24 hours")

        logger.info(f"Checking for posts since: {datetime.fromtimestamp(last_checked_ms/1000, IST)}")

        # Get new user posts
        new_posts = self.get_new_user_posts(last_checked_ms)

        if not new_posts:
            logger.info("No new user posts found")
            # Update state even if no posts found
            state['last_checked_ms'] = int(datetime.now(IST).timestamp() * 1000)
            state['last_checked_at'] = datetime.now(IST).isoformat()
            self._save_state(state)
            return {"posts_engaged": 0, "total_likes": 0, "total_comments": 0}

        logger.info(f"Found {len(new_posts)} new user posts to engage with")

        total_stats = {"posts_engaged": 0, "total_likes": 0, "total_comments": 0}

        for post in new_posts:
            try:
                stats = self.engage_with_post(post)
                total_stats["posts_engaged"] += 1
                total_stats["total_likes"] += stats["likes"]
                total_stats["total_comments"] += stats["comments"]

                # Wait before next post
                if post != new_posts[-1]:
                    logger.info(f"\nWaiting {delay_between_posts}s before next post...")
                    time.sleep(delay_between_posts)

            except Exception as e:
                logger.error(f"Error engaging with post {post['id']}: {e}")
                continue

        # Update state with current timestamp
        state['last_checked_ms'] = int(datetime.now(IST).timestamp() * 1000)
        state['last_checked_at'] = datetime.now(IST).isoformat()
        state['last_run_stats'] = total_stats
        self._save_state(state)

        logger.info("\n" + "=" * 60)
        logger.info("ENGAGEMENT CHECK COMPLETE")
        logger.info(f"  Posts engaged: {total_stats['posts_engaged']}")
        logger.info(f"  Total likes: {total_stats['total_likes']}")
        logger.info(f"  Total comments: {total_stats['total_comments']}")
        logger.info("=" * 60)

        return total_stats


# Singleton instance
_service = None


def get_user_post_engagement_service() -> UserPostEngagementService:
    """Get the singleton instance."""
    global _service
    if _service is None:
        _service = UserPostEngagementService()
    return _service


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="User Post Engagement Service")
    parser.add_argument("--run", action="store_true", help="Run engagement check now")
    parser.add_argument("--reset-state", action="store_true", help="Reset last checked timestamp")
    parser.add_argument("--show-state", action="store_true", help="Show current state")

    args = parser.parse_args()

    service = get_user_post_engagement_service()

    if args.reset_state:
        state = {"last_checked_ms": 0}
        service._save_state(state)
        print("State reset to beginning")

    elif args.show_state:
        state = service._load_state()
        print(json.dumps(state, indent=2))

    elif args.run:
        stats = service.run_engagement_check()
        print(f"\nEngaged with {stats['posts_engaged']} posts")
        print(f"Added {stats['total_likes']} likes and {stats['total_comments']} comments")

    else:
        parser.print_help()
