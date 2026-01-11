"""
Firestore Service for Auto Quote Poster.

This service handles:
- Connecting to Firebase Firestore
- Pushing quotes to the posts collection with full post structure
- Managing posts
"""

import os
import uuid
import time
from datetime import datetime
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

# Firestore configuration
FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
)
POSTS_COLLECTION = "posts"
DHYANI_USER_ID = "7es9AYnaW7afNtMeOBtXl8Z2ILF3"
DHYANI_CREATOR_NAME = "Dhyani"


class FirestoreService:
    """Service for managing posts in Firestore."""

    def __init__(self):
        """Initialize the Firestore service."""
        self.db = None
        self._initialize_firebase()

    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK."""
        try:
            # Check if already initialized
            if firebase_admin._apps:
                self.db = firestore.client()
                print("[INFO] Using existing Firebase app")
                return

            # Check if credentials file exists
            if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
                print(f"[WARNING] Firebase credentials not found at: {FIREBASE_CREDENTIALS_PATH}")
                print("[WARNING] Firestore operations will fail until credentials are configured")
                return

            # Initialize with credentials
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            print("[SUCCESS] Firebase initialized successfully")

        except Exception as e:
            print(f"[ERROR] Failed to initialize Firebase: {e}")
            self.db = None

    def is_connected(self) -> bool:
        """Check if Firestore is connected."""
        return self.db is not None

    def push_quote(
        self,
        quote: str,
        saying: str,
        description: str,
        created_at: Optional[datetime] = None,
        image_url: Optional[str] = None,
        post_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Push a quote to Firestore posts collection.

        Args:
            quote: The main quote text (will be the content)
            saying: A short saying or tagline (added to description)
            description: Description or context for the quote
            created_at: Timestamp (defaults to now)
            image_url: Optional URL of the quote image
            post_id: Optional pre-generated post ID

        Returns:
            Document ID if successful, None otherwise
        """
        if not self.is_connected():
            print("[ERROR] Firestore not connected. Cannot push quote.")
            return None

        # Generate unique ID for the post if not provided
        if post_id is None:
            post_id = str(uuid.uuid4())

        # Get timestamp in milliseconds
        if created_at is None:
            created_at_ms = int(time.time() * 1000)
        else:
            created_at_ms = int(created_at.timestamp() * 1000)

        # Prepare full post document data
        doc_data = {
            "audioBackgroundUrl": None,
            "audioUrl": None,
            "commentCount": 0,
            "composition": "SEPARATE_CONTENT",
            "content": quote,
            "createdAt": created_at_ms,
            "createdBy": DHYANI_USER_ID,
            "creatorName": DHYANI_CREATOR_NAME,
            "deleted": False,
            "deletedAt": None,
            "deletedByAdmin": False,
            "description": f"{saying} - {description}",
            "globallyHidden": False,
            "imageUrl": image_url,
            "isAudioBackgroundFromGallery": False,
            "isLikedByCurrentUser": None,
            "isReportedByCurrentUserStatus": None,
            "isViewedByCurrentUser": None,
            "isYouTubeVideo": False,
            "lastEditedAt": None,
            "likeCount": 0,
            "location": "",
            "selfID": post_id,
            "videoUrl": None,
            "viewCount": 0,
        }

        try:
            # Add to posts collection with the generated ID
            self.db.collection(POSTS_COLLECTION).document(post_id).set(doc_data)

            print(f"[SUCCESS] Quote pushed to Firestore posts collection with ID: {post_id}")
            return post_id

        except Exception as e:
            print(f"[ERROR] Failed to push quote: {e}")
            return None

    def get_recent_quotes(self, limit: int = 10) -> list[dict]:
        """
        Get recent posts from Firestore created by Dhyani.

        Args:
            limit: Maximum number of posts to return

        Returns:
            List of post documents
        """
        if not self.is_connected():
            print("[ERROR] Firestore not connected.")
            return []

        try:
            docs = (
                self.db.collection(POSTS_COLLECTION)
                .where("createdBy", "==", DHYANI_USER_ID)
                .order_by("createdAt", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )

            posts = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                posts.append(data)

            return posts

        except Exception as e:
            print(f"[ERROR] Failed to get posts: {e}")
            return []

    def get_quote_count(self) -> int:
        """Get total number of posts by Dhyani."""
        if not self.is_connected():
            return 0

        try:
            docs = (
                self.db.collection(POSTS_COLLECTION)
                .where("createdBy", "==", DHYANI_USER_ID)
                .stream()
            )
            return sum(1 for _ in docs)
        except Exception as e:
            print(f"[ERROR] Failed to count posts: {e}")
            return 0

    def delete_quote(self, doc_id: str) -> bool:
        """
        Delete a post by document ID.

        Args:
            doc_id: The Firestore document ID

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            print("[ERROR] Firestore not connected.")
            return False

        try:
            self.db.collection(POSTS_COLLECTION).document(doc_id).delete()
            print(f"[SUCCESS] Deleted post: {doc_id}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to delete post: {e}")
            return False


# Singleton instance
_firestore_service = None


def get_firestore_service() -> FirestoreService:
    """Get the singleton instance of the Firestore service."""
    global _firestore_service
    if _firestore_service is None:
        _firestore_service = FirestoreService()
    return _firestore_service


if __name__ == "__main__":
    # Quick test
    service = get_firestore_service()

    if service.is_connected():
        # Test push
        doc_id = service.push_quote(
            quote="The only way to do great work is to love what you do.",
            saying="Follow your passion",
            description="A motivational quote about finding purpose in work."
        )

        if doc_id:
            print(f"\nPushed post with ID: {doc_id}")

            # Get recent posts
            posts = service.get_recent_quotes(5)
            print(f"\nRecent posts by Dhyani ({len(posts)}):")
            for p in posts:
                print(f"  - {p.get('content', 'N/A')[:50]}...")
    else:
        print("\n[INFO] To use Firestore, place your Firebase credentials at:")
        print(f"       {FIREBASE_CREDENTIALS_PATH}")
        print("\n       Or set FIREBASE_CREDENTIALS_PATH environment variable.")
