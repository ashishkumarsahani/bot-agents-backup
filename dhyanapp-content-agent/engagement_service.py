"""
Engagement Service for DhyanApp Bot Posts.

This service handles:
- Adding likes from bot accounts to posts
- Generating and posting comments based on personas
- Creating reply threads between bot accounts
- Managing conversation flow under posts
"""

import os
import json
import random
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional, List

from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
IST = ZoneInfo("Asia/Kolkata")
BOT_ACCOUNTS_FILE = Path(__file__).parent / "bot_accounts.json"

FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
)


class EngagementService:
    """Service for generating bot engagement on posts."""

    def __init__(self):
        """Initialize the engagement service."""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.accounts = self._load_accounts()
        self._initialize_firebase()

    def _initialize_firebase(self):
        """Initialize Firebase."""
        try:
            if not firebase_admin._apps:
                if os.path.exists(FIREBASE_CREDENTIALS_PATH):
                    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                    firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            logger.info("[SUCCESS] Firebase initialized for engagement")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize Firebase: {e}")
            self.db = None

    def _load_accounts(self) -> dict:
        """Load bot accounts from JSON file."""
        try:
            with open(BOT_ACCOUNTS_FILE, 'r') as f:
                data = json.load(f)
                return data.get('accounts', {})
        except Exception as e:
            logger.error(f"[ERROR] Failed to load bot accounts: {e}")
            return {}

    def get_post_content(self, post_id: str) -> Optional[dict]:
        """
        Get post content from Firestore.

        Args:
            post_id: The post document ID

        Returns:
            Post data dictionary or None
        """
        try:
            doc = self.db.collection('posts').document(post_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"[ERROR] Failed to get post: {e}")
            return None

    def get_existing_comments(self, post_id: str) -> List[dict]:
        """
        Get existing comments on a post.

        Args:
            post_id: The post document ID

        Returns:
            List of comment dictionaries
        """
        try:
            comments_ref = self.db.collection('posts').document(post_id).collection('Comments')
            comments = comments_ref.order_by('createdAt').stream()
            return [{'id': c.id, **c.to_dict()} for c in comments]
        except Exception as e:
            logger.error(f"[ERROR] Failed to get comments: {e}")
            return []

    def add_like(self, post_id: str, user_id: str) -> bool:
        """
        Add a like to a post.

        Args:
            post_id: The post document ID
            user_id: The user ID liking the post

        Returns:
            True if successful

        Note: likeCount is incremented automatically by Cloud Function (handleLikeCreated)
        """
        try:
            timestamp = int(datetime.now(IST).timestamp() * 1000)

            # Add to Likes subcollection
            # Cloud Function handleLikeCreated will increment likeCount automatically
            like_ref = self.db.collection('posts').document(post_id).collection('Likes').document(user_id)
            like_ref.set({
                'userId': user_id,
                'timestamp': timestamp
            })

            logger.info(f"[SUCCESS] Like added by {user_id}")
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to add like: {e}")
            return False

    def add_comment(self, post_id: str, user_id: str, comment_text: str, reply_to: Optional[str] = None) -> Optional[str]:
        """
        Add a comment to a post.

        Args:
            post_id: The post document ID
            user_id: The user ID commenting
            comment_text: The comment content
            reply_to: Optional comment ID being replied to

        Returns:
            Comment ID if successful

        Note: commentCount is incremented automatically by Cloud Function (handleCommentCreated)
        """
        try:
            timestamp = int(datetime.now(IST).timestamp() * 1000)
            comment_id = f"{timestamp}{user_id}"

            # Add to Comments subcollection
            # Cloud Function handleCommentCreated will increment commentCount automatically
            comment_ref = self.db.collection('posts').document(post_id).collection('Comments').document(comment_id)
            comment_ref.set({
                'commentId': comment_id,
                'comment': comment_text,
                'createdBy': user_id,
                'createdAt': timestamp,
                'repliedTo': reply_to
            })

            logger.info(f"[SUCCESS] Comment added by {user_id}: {comment_text[:50]}...")
            return comment_id
        except Exception as e:
            logger.error(f"[ERROR] Failed to add comment: {e}")
            return None

    def _get_commenter_name(self, user_id: str) -> Optional[str]:
        """Get the display name for a user ID from bot accounts."""
        for key, account in self.accounts.items():
            if account.get('user_id') == user_id:
                return account.get('name')
        return None

    def generate_anecdote(self, account: dict, post_content: str, post_language: str,
                          existing_comments: List[dict] = None, poster_name: str = None) -> str:
        """
        Generate a short anecdote or story from the commenter's tradition.

        Args:
            account: Account dictionary with persona details
            post_content: The post content to relate to
            post_language: Language of the post (hindi/english)
            existing_comments: List of existing comments for context
            poster_name: Name of the original poster

        Returns:
            Generated anecdote text (40-80 words)
        """
        # Always match the post language
        comment_lang = "Hindi" if post_language == 'hindi' else "English"

        # Build people to tag
        people_to_tag = []
        if poster_name:
            people_to_tag.append(poster_name)
        if existing_comments:
            for c in existing_comments[-3:]:
                commenter_name = self._get_commenter_name(c.get('createdBy'))
                if commenter_name and commenter_name != account.get('name') and commenter_name not in people_to_tag:
                    people_to_tag.append(commenter_name)

        tag_instruction = ""
        if people_to_tag and random.random() < 0.5:
            selected_tag = random.choice(people_to_tag)
            tag_instruction = f"\nYou may tag @{selected_tag} when sharing your story."

        prompt = f"""Post content (respond to THIS):
{post_content[:300]}

You are: {account.get('name')}
Your tradition: {account.get('persona', '')}
Saints/Teachers you follow: {', '.join(account.get('follows', [])[:4])}
Scriptures: {', '.join(account.get('scriptures', [])[:3])}
{tag_instruction}

Share a SHORT anecdote or story (40-80 words) from YOUR tradition that CONNECTS to what was shared in the post.

Guidelines:
- Read the post carefully — your story must relate to its specific content
- Pick ONE real story from your tradition's saints, scriptures, or teachings
- Tell it naturally, like sharing with a close spiritual friend
- End with a warm reflection or "This reminds me..." connection
- Write in {comment_lang}
- Sound like a seeker sharing from personal experience, not a teacher giving a lesson

DO NOT:
- Make up fake stories — use real incidents from your tradition
- Be preachy or lecture-like
- Write more than 80 words
- Ignore the post content — your story must connect to it
- Be generic — be specific to YOUR tradition

Return ONLY the anecdote text."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, sharing a short traditional story that connects to the post."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.85,
                max_tokens=200
            )
            anecdote = response.choices[0].message.content.strip()
            anecdote = anecdote.strip('"\'')
            return anecdote
        except Exception as e:
            logger.error(f"[ERROR] Failed to generate anecdote: {e}")
            return ""

    def generate_comment(self, account: dict, post_content: str, post_language: str,
                         existing_comments: List[dict] = None, reply_to_comment: dict = None,
                         poster_name: str = None, next_commenter_name: str = None) -> str:
        """
        Generate a natural, thoughtful comment based on the account's persona.

        Args:
            account: Account dictionary with persona details
            post_content: The post content to comment on
            post_language: Language of the post (hindi/english)
            existing_comments: List of existing comments for context
            reply_to_comment: Specific comment being replied to
            poster_name: Name of the original poster
            next_commenter_name: Name of the next bot to comment (to tag)

        Returns:
            Generated comment text
        """
        # Always match the post language
        comment_lang = "Hindi" if post_language == 'hindi' else "English"

        # Build list of people to potentially tag
        people_to_tag = []
        if poster_name:
            people_to_tag.append(poster_name)
        if existing_comments:
            for c in existing_comments[-4:]:
                commenter_name = self._get_commenter_name(c.get('createdBy'))
                if commenter_name and commenter_name != account.get('name') and commenter_name not in people_to_tag:
                    people_to_tag.append(commenter_name)

        # Build context
        context = f"""Post Content (summarized):
{post_content[:400]}

You are: {account.get('name')}
- Your vibe: {account.get('conversational_style', '')}
- You follow: {', '.join(account.get('follows', [])[:3])}
"""

        # Tagging instructions
        tag_instruction = ""
        if people_to_tag and random.random() < 0.6:  # 60% chance to tag someone
            selected_tags = random.sample(people_to_tag, min(random.randint(1, 2), len(people_to_tag)))
            tag_instruction = f"\nYou may tag one or two of these people in your comment: {', '.join(['@' + name for name in selected_tags])}"

        if reply_to_comment:
            reply_to_name = self._get_commenter_name(reply_to_comment.get('createdBy')) or "them"
            context += f"""
You're replying to @{reply_to_name} who said:
"{reply_to_comment.get('comment', '')}"
{tag_instruction}

Keep it casual! Agree, disagree, or add your take. Like chatting with a friend.
"""
        elif existing_comments:
            context += f"""
Some comments already here:
"""
            for c in existing_comments[-3:]:
                commenter = self._get_commenter_name(c.get('createdBy')) or "Someone"
                context += f"- @{commenter}: {c.get('comment', '')[:60]}...\n"
            context += f"""
{tag_instruction}

Jump into the conversation! React to what others said or add your own thought.
"""
        else:
            context += f"""
You're first to comment! {f"Tag @{poster_name} if you want." if poster_name else ""}

Drop a friendly, genuine reaction to the post.
"""

        # Build tagging requirements
        tag_requirements = ""
        if poster_name:
            tag_requirements += f"\n- You MUST address the post creator as @{poster_name} ji in your comment"
        if next_commenter_name:
            tag_requirements += f"\n- You MUST also tag @{next_commenter_name} ji in your comment to bring them into the conversation"

        prompt = f"""{context}

Write a comment in {comment_lang} as a fellow spiritual seeker and mentor:
- 15-40 words — thoughtful, warm, and genuine
- The post text is your PRIMARY context — respond to what was actually written{tag_requirements}
- Share from your own spiritual journey and tradition naturally
- You are a seeker on the same path, sometimes a gentle mentor — never a lecturer
- Reference your scriptures, saints, or teachings only when it flows naturally
- Sound like someone others would seek out for spiritual friendship

Your unique voice:
- If you follow Kabir, you might share a doha that moved you
- If you follow Ramana, you might gently point to self-inquiry
- If you follow Krishna bhakti, express devotion naturally
- If you're into Tantra, speak of Shakti or consciousness from experience
- If you're a storyteller, weave in a moment from the epics

AVOID:
- Generic praise ("beautiful post!", "so true!")
- Being preachy or talking down to others
- Excessive casual words like "yaar", "wow"
- Overly formal or academic language
- Ignoring what the post actually says

Return ONLY the comment text."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are {account['name']}, a genuine spiritual seeker and mentor. You comment naturally, sharing insights from your own journey."},
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
            return "🙏" if comment_lang == "Hindi" else "Beautifully said! 🙏"

    def engage_with_post(self, post_id: str, poster_account_key: str,
                         min_delay_minutes: int = 5, max_delay_minutes: int = 10,
                         test_mode: bool = False) -> dict:
        """
        Full engagement pipeline: likes and comments from non-poster accounts.

        Args:
            post_id: The post document ID
            poster_account_key: The account key of the poster (to exclude)
            min_delay_minutes: Minimum delay between comments in minutes (default 5)
            max_delay_minutes: Maximum delay between comments in minutes (default 10)
            test_mode: If True, use 10-30 second delays instead of minutes

        Returns:
            Dictionary with engagement stats
        """
        if test_mode:
            min_delay_sec = 10  # 10 seconds
            max_delay_sec = 30  # 30 seconds
            logger.info("TEST MODE: Using 10-30 second delays")
        else:
            min_delay_sec = min_delay_minutes * 60
            max_delay_sec = max_delay_minutes * 60
            logger.info(f"Using {min_delay_minutes}-{max_delay_minutes} minute delays between comments")
        logger.info(f"\n{'='*60}")
        logger.info(f"ENGAGING WITH POST: {post_id}")
        logger.info(f"{'='*60}")

        # Get post content
        post_data = self.get_post_content(post_id)
        if not post_data:
            logger.error("Could not fetch post content")
            return {"likes": 0, "comments": 0}

        post_content = post_data.get('content', '')
        post_language = post_data.get('_language', 'english')

        # Get poster name
        poster_name = None
        if poster_account_key in self.accounts:
            poster_name = self.accounts[poster_account_key].get('name')
        else:
            poster_name = post_data.get('creatorName')

        # Get non-poster accounts
        engaging_accounts = []
        for key, account in self.accounts.items():
            if key != poster_account_key:
                account_copy = account.copy()
                account_copy['account_key'] = key
                engaging_accounts.append(account_copy)

        random.shuffle(engaging_accounts)

        stats = {"likes": 0, "comments": 0, "replies": 0}

        # Step 1: Add likes from 4 random accounts
        likers = random.sample(engaging_accounts, min(4, len(engaging_accounts)))
        logger.info(f"\nAdding likes from: {[a['name'] for a in likers]}")

        for account in likers:
            if self.add_like(post_id, account['user_id']):
                stats["likes"] += 1
            time.sleep(random.randint(2, 5))  # Small random delay

        # Step 2: First round of comments (all accounts comment)
        # Select 1-2 accounts to share anecdotes instead of regular comments
        num_anecdote_commenters = random.randint(1, 2)
        anecdote_commenters = random.sample(engaging_accounts, min(num_anecdote_commenters, len(engaging_accounts)))
        anecdote_commenter_ids = [a['user_id'] for a in anecdote_commenters]

        logger.info(f"\nFirst round of comments from all {len(engaging_accounts)} accounts")
        logger.info(f"Anecdote sharers: {[a['name'] for a in anecdote_commenters]}")

        stats["anecdotes"] = 0

        for idx, account in enumerate(engaging_accounts):
            existing = self.get_existing_comments(post_id)

            # Determine the next commenter to tag
            next_commenter_name = None
            if idx + 1 < len(engaging_accounts):
                next_commenter_name = engaging_accounts[idx + 1].get('name')

            # Check if this account should share an anecdote
            if account['user_id'] in anecdote_commenter_ids:
                comment = self.generate_anecdote(
                    account, post_content, post_language,
                    existing, poster_name
                )
                if comment:
                    comment_type = "anecdote"
                    stats["anecdotes"] += 1
                else:
                    # Fallback to regular comment if anecdote generation fails
                    comment = self.generate_comment(
                        account, post_content, post_language,
                        existing, poster_name=poster_name,
                        next_commenter_name=next_commenter_name
                    )
                    comment_type = "comment"
            else:
                comment = self.generate_comment(
                    account, post_content, post_language,
                    existing, poster_name=poster_name,
                    next_commenter_name=next_commenter_name
                )
                comment_type = "comment"

            if self.add_comment(post_id, account['user_id'], comment):
                stats["comments"] += 1
                logger.info(f"  {account['name']} [{comment_type}]: {comment[:70]}...")

            # Delay between comments (5-10 minutes with randomness)
            delay = random.randint(min_delay_sec, max_delay_sec)
            logger.info(f"    Waiting {delay // 60} min {delay % 60} sec before next comment...")
            time.sleep(delay)

        # Step 3: Reply round - some accounts reply to existing comments
        logger.info(f"\nReply round - creating conversation threads")

        existing_comments = self.get_existing_comments(post_id)

        # Select 2-3 accounts to reply
        repliers = random.sample(engaging_accounts, min(3, len(engaging_accounts)))

        for account in repliers:
            # Find a comment to reply to (not their own)
            other_comments = [c for c in existing_comments if c.get('createdBy') != account['user_id']]

            if other_comments:
                # Reply to a random comment
                target_comment = random.choice(other_comments)

                reply = self.generate_comment(
                    account, post_content, post_language,
                    existing_comments, target_comment, poster_name
                )

                if self.add_comment(post_id, account['user_id'], reply, target_comment.get('commentId')):
                    stats["replies"] += 1
                    logger.info(f"  {account['name']} replied to: {target_comment.get('comment', '')[:30]}...")
                    logger.info(f"    Reply: {reply[:60]}...")

                # Delay between replies (5-10 minutes with randomness)
                delay = random.randint(min_delay_sec, max_delay_sec)
                logger.info(f"    Waiting {delay // 60} min {delay % 60} sec before next reply...")
                time.sleep(delay)

        logger.info(f"\n{'='*60}")
        logger.info(f"ENGAGEMENT COMPLETE")
        logger.info(f"  Likes: {stats['likes']}")
        logger.info(f"  Comments: {stats['comments']}")
        logger.info(f"  Anecdotes: {stats.get('anecdotes', 0)}")
        logger.info(f"  Replies: {stats['replies']}")
        logger.info(f"{'='*60}")

        return stats


# Singleton instance
_engagement_service = None


def get_engagement_service() -> EngagementService:
    """Get the singleton instance of the engagement service."""
    global _engagement_service
    if _engagement_service is None:
        _engagement_service = EngagementService()
    return _engagement_service


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Engagement Service")
    parser.add_argument("--post-id", type=str, help="Post ID to engage with")
    parser.add_argument("--poster", type=str, default="dhyani", help="Account key of the poster to exclude")
    parser.add_argument("--min-delay", type=int, default=5, help="Minimum delay between comments in minutes")
    parser.add_argument("--max-delay", type=int, default=10, help="Maximum delay between comments in minutes")
    parser.add_argument("--test-mode", action="store_true", help="Use shorter delays for testing (10-30 seconds)")

    args = parser.parse_args()

    if args.post_id:
        service = get_engagement_service()

        stats = service.engage_with_post(
            args.post_id,
            args.poster,
            args.min_delay,
            args.max_delay,
            test_mode=args.test_mode
        )
        print(f"\nEngagement stats: {stats}")
    else:
        parser.print_help()
