"""
Festival History and Custom Topics Manager.

This service handles:
- Managing custom topics to post about for specific days
- Tracking history of all posted festivals
- Reading/writing to text files for persistence
"""

import os
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# File paths
DATA_DIR = Path(__file__).parent / "festival_data"
CUSTOM_TOPICS_FILE = DATA_DIR / "custom_topics.json"
POSTED_HISTORY_FILE = DATA_DIR / "posted_history.json"


class FestivalHistoryManager:
    """Manager for festival history and custom topics."""

    def __init__(self):
        """Initialize the history manager."""
        # Create data directory if it doesn't exist
        DATA_DIR.mkdir(exist_ok=True)

        # Initialize files if they don't exist
        self._initialize_files()

    def _initialize_files(self):
        """Initialize data files if they don't exist."""
        if not CUSTOM_TOPICS_FILE.exists():
            self._save_json(CUSTOM_TOPICS_FILE, {
                "description": "Custom topics to post about. Add date-specific or general topics here.",
                "date_specific": {},  # Format: {"2024-01-26": ["Republic Day", "National Pride"]}
                "general": []  # General topics to post any time
            })

        if not POSTED_HISTORY_FILE.exists():
            self._save_json(POSTED_HISTORY_FILE, {
                "description": "History of all posted festivals and topics",
                "posts": []
            })

    def _load_json(self, filepath: Path) -> dict:
        """Load JSON from file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to load {filepath}: {e}")
            return {}

    def _save_json(self, filepath: Path, data: dict):
        """Save JSON to file."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Failed to save {filepath}: {e}")

    # ==================== CUSTOM TOPICS ====================

    def get_custom_topics_for_date(self, target_date: date = None) -> list[str]:
        """
        Get custom topics for a specific date.

        Args:
            target_date: Date to get topics for (default: today)

        Returns:
            List of custom topics
        """
        if target_date is None:
            target_date = date.today()

        data = self._load_json(CUSTOM_TOPICS_FILE)
        date_str = target_date.strftime("%Y-%m-%d")

        topics = data.get("date_specific", {}).get(date_str, [])

        print(f"[INFO] Found {len(topics)} custom topics for {date_str}")
        return topics

    def get_general_topics(self) -> list[str]:
        """Get general topics that can be posted any time."""
        data = self._load_json(CUSTOM_TOPICS_FILE)
        return data.get("general", [])

    def add_custom_topic(self, topic: str, target_date: date = None):
        """
        Add a custom topic for a specific date.

        Args:
            topic: Topic to add
            target_date: Date for the topic (None for general)
        """
        data = self._load_json(CUSTOM_TOPICS_FILE)

        if target_date:
            date_str = target_date.strftime("%Y-%m-%d")
            if "date_specific" not in data:
                data["date_specific"] = {}
            if date_str not in data["date_specific"]:
                data["date_specific"][date_str] = []
            if topic not in data["date_specific"][date_str]:
                data["date_specific"][date_str].append(topic)
                print(f"[SUCCESS] Added topic '{topic}' for {date_str}")
        else:
            if "general" not in data:
                data["general"] = []
            if topic not in data["general"]:
                data["general"].append(topic)
                print(f"[SUCCESS] Added general topic '{topic}'")

        self._save_json(CUSTOM_TOPICS_FILE, data)

    def remove_custom_topic(self, topic: str, target_date: date = None) -> bool:
        """
        Remove a custom topic.

        Args:
            topic: Topic to remove
            target_date: Date of the topic (None for general)

        Returns:
            True if removed, False otherwise
        """
        data = self._load_json(CUSTOM_TOPICS_FILE)

        if target_date:
            date_str = target_date.strftime("%Y-%m-%d")
            if date_str in data.get("date_specific", {}):
                if topic in data["date_specific"][date_str]:
                    data["date_specific"][date_str].remove(topic)
                    self._save_json(CUSTOM_TOPICS_FILE, data)
                    print(f"[SUCCESS] Removed topic '{topic}' from {date_str}")
                    return True
        else:
            if topic in data.get("general", []):
                data["general"].remove(topic)
                self._save_json(CUSTOM_TOPICS_FILE, data)
                print(f"[SUCCESS] Removed general topic '{topic}'")
                return True

        print(f"[WARNING] Topic '{topic}' not found")
        return False

    def clear_topics_for_date(self, target_date: date):
        """Clear all custom topics for a specific date."""
        data = self._load_json(CUSTOM_TOPICS_FILE)
        date_str = target_date.strftime("%Y-%m-%d")

        if date_str in data.get("date_specific", {}):
            del data["date_specific"][date_str]
            self._save_json(CUSTOM_TOPICS_FILE, data)
            print(f"[SUCCESS] Cleared topics for {date_str}")

    # ==================== POST HISTORY ====================

    def record_post(self, festival_name: str, language: str, post_id: str, post_type: str = "festival"):
        """
        Record a posted festival/topic.

        Args:
            festival_name: Name of the festival/topic
            language: Language of the post
            post_id: Firestore post ID
            post_type: Type of post (festival/custom)
        """
        data = self._load_json(POSTED_HISTORY_FILE)

        if "posts" not in data:
            data["posts"] = []

        record = {
            "date": date.today().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(),
            "festival_name": festival_name,
            "language": language,
            "post_id": post_id,
            "post_type": post_type
        }

        data["posts"].append(record)
        self._save_json(POSTED_HISTORY_FILE, data)

        print(f"[HISTORY] Recorded: {festival_name} ({language})")

    def get_posted_festivals(self, target_date: date = None) -> list[dict]:
        """
        Get all posts for a specific date.

        Args:
            target_date: Date to check (default: today)

        Returns:
            List of posted records
        """
        if target_date is None:
            target_date = date.today()

        data = self._load_json(POSTED_HISTORY_FILE)
        date_str = target_date.strftime("%Y-%m-%d")

        posts = [p for p in data.get("posts", []) if p.get("date") == date_str]
        return posts

    def is_already_posted(self, festival_name: str, language: str, target_date: date = None) -> bool:
        """
        Check if a festival has already been posted today.

        Args:
            festival_name: Name of the festival
            language: Language to check
            target_date: Date to check

        Returns:
            True if already posted
        """
        posts = self.get_posted_festivals(target_date)

        for post in posts:
            if (post.get("festival_name", "").lower() == festival_name.lower() and
                post.get("language", "").lower() == language.lower()):
                return True

        return False

    def get_all_history(self) -> list[dict]:
        """Get all posting history."""
        data = self._load_json(POSTED_HISTORY_FILE)
        return data.get("posts", [])

    def get_history_summary(self) -> dict:
        """Get a summary of posting history."""
        posts = self.get_all_history()

        # Count by festival
        festival_counts = {}
        for post in posts:
            name = post.get("festival_name", "Unknown")
            festival_counts[name] = festival_counts.get(name, 0) + 1

        # Count by date
        date_counts = {}
        for post in posts:
            post_date = post.get("date", "Unknown")
            date_counts[post_date] = date_counts.get(post_date, 0) + 1

        return {
            "total_posts": len(posts),
            "unique_festivals": len(festival_counts),
            "posts_per_festival": festival_counts,
            "posts_per_date": date_counts
        }

    def display_all_records(self):
        """Display all history records in a formatted way."""
        posts = self.get_all_history()

        print(f"\n{'='*70}")
        print("FESTIVAL POST HISTORY")
        print(f"{'='*70}")
        print(f"Total Posts: {len(posts)}")
        print(f"{'='*70}\n")

        # Group by date
        by_date = {}
        for post in posts:
            post_date = post.get("date", "Unknown")
            if post_date not in by_date:
                by_date[post_date] = []
            by_date[post_date].append(post)

        for post_date in sorted(by_date.keys(), reverse=True):
            print(f"\n[{post_date}]")
            for post in by_date[post_date]:
                print(f"  - {post.get('festival_name')} ({post.get('language')})")
                print(f"    Type: {post.get('post_type')}, ID: {post.get('post_id')}")


# Singleton instance
_history_manager = None


def get_festival_history_manager() -> FestivalHistoryManager:
    """Get the singleton instance of the history manager."""
    global _history_manager
    if _history_manager is None:
        _history_manager = FestivalHistoryManager()
    return _history_manager


if __name__ == "__main__":
    # Quick test
    manager = get_festival_history_manager()

    print("\n" + "="*60)
    print("Festival History Manager Test")
    print("="*60)

    # Add some test topics
    print("\n[TEST] Adding custom topics...")
    manager.add_custom_topic("Republic Day", date(2024, 1, 26))
    manager.add_custom_topic("Meditation Benefits")  # General topic

    # Get topics for today
    print(f"\n[TEST] Topics for today: {manager.get_custom_topics_for_date()}")
    print(f"[TEST] General topics: {manager.get_general_topics()}")

    # Record a test post
    print("\n[TEST] Recording test post...")
    manager.record_post("Test Festival", "english", "test-123", "test")

    # Get history
    print(f"\n[TEST] Today's posts: {manager.get_posted_festivals()}")

    # Check if posted
    print(f"[TEST] Is 'Test Festival' posted? {manager.is_already_posted('Test Festival', 'english')}")

    # Display all records
    manager.display_all_records()
