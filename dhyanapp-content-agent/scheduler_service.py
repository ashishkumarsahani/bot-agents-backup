"""
Scheduler Service for Auto Quote Poster.

This service handles:
- Scheduling daily quote generation and posting at 6 AM IST
- Managing the APScheduler for background jobs
- Running the complete quote posting pipeline with image generation
"""

import os
import uuid
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from vector_store_service import get_vector_store_service
from quote_generator_service import get_quote_generator_service
from firestore_service import get_firestore_service
from image_generator_service import get_image_generator_service

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# IST timezone
IST = ZoneInfo("Asia/Kolkata")


def generate_and_post_quote():
    """
    Generate a quote from random chunks, create an image, and post to Firestore.

    This is the main job that runs daily at 6 AM IST.
    """
    logger.info("=" * 60)
    logger.info("STARTING DAILY QUOTE GENERATION WITH IMAGE")
    logger.info(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    logger.info("=" * 60)

    try:
        # Check vector store
        vs = get_vector_store_service()
        stats = vs.get_stats()

        if stats.get('total_chunks', 0) == 0:
            logger.warning("Vector store is empty. Cannot generate quotes.")
            logger.warning("Please index some content using the Streamlit app.")
            return False

        logger.info(f"Vector store has {stats['total_chunks']} chunks")

        # Generate quote
        generator = get_quote_generator_service()
        quote_data = generator.generate_quote_from_chunks(num_chunks=3)

        if not quote_data:
            logger.error("Failed to generate quote")
            return False

        logger.info(f"Generated quote: {quote_data['quote'][:50]}...")

        # Generate post ID first (needed for image upload)
        post_id = str(uuid.uuid4())
        logger.info(f"Post ID: {post_id}")

        # Generate image with quote
        logger.info("Generating quote image with DALL-E 3...")
        image_service = get_image_generator_service()
        image_url = image_service.generate_and_upload(
            quote=quote_data['quote'],
            saying=quote_data['saying'],
            post_id=post_id
        )

        if image_url:
            logger.info(f"Image generated and uploaded successfully")
        else:
            logger.warning("Failed to generate image, posting without image")

        # Push to Firestore
        firestore = get_firestore_service()

        if not firestore.is_connected():
            logger.error("Firestore not connected. Cannot post quote.")
            return False

        doc_id = firestore.push_quote(
            quote=quote_data['quote'],
            saying=quote_data['saying'],
            description=quote_data['description'],
            created_at=datetime.now(IST),
            image_url=image_url,
            post_id=post_id
        )

        if doc_id:
            logger.info(f"Quote posted successfully! Document ID: {doc_id}")
            if image_url:
                logger.info(f"Image URL: {image_url[:80]}...")
            logger.info("=" * 60)
            return True
        else:
            logger.error("Failed to post quote to Firestore")
            return False

    except Exception as e:
        logger.error(f"Error in daily quote generation: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


class QuoteSchedulerService:
    """Service for scheduling quote generation and posting."""

    def __init__(self, blocking: bool = False):
        """
        Initialize the scheduler service.

        Args:
            blocking: If True, use BlockingScheduler (for standalone script)
                     If False, use BackgroundScheduler (for integration with other apps)
        """
        if blocking:
            self.scheduler = BlockingScheduler(timezone=IST)
        else:
            self.scheduler = BackgroundScheduler(timezone=IST)

        self.job_id = "daily_quote_post"

    def setup_daily_job(self, hour: int = 6, minute: int = 0):
        """
        Set up the daily quote posting job.

        Args:
            hour: Hour to run (0-23) in IST
            minute: Minute to run (0-59)
        """
        # Create cron trigger for 6 AM IST
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=IST
        )

        # Add job
        self.scheduler.add_job(
            generate_and_post_quote,
            trigger=trigger,
            id=self.job_id,
            name="Daily Quote Post",
            replace_existing=True
        )

        logger.info(f"Scheduled daily quote posting at {hour:02d}:{minute:02d} IST")

    def start(self):
        """Start the scheduler."""
        logger.info("Starting scheduler...")
        self.scheduler.start()
        logger.info("Scheduler started successfully")

    def stop(self):
        """Stop the scheduler."""
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    def run_now(self):
        """Run the quote generation immediately (for testing)."""
        logger.info("Running quote generation now (manual trigger)...")
        return generate_and_post_quote()

    def get_next_run_time(self) -> str:
        """Get the next scheduled run time."""
        job = self.scheduler.get_job(self.job_id)
        if job and job.next_run_time:
            return job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')
        return "Not scheduled"

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self.scheduler.running


def run_scheduler_daemon():
    """
    Run the scheduler as a blocking daemon.

    This function will block and run until interrupted.
    """
    logger.info("=" * 60)
    logger.info("AUTO QUOTE POSTER SCHEDULER")
    logger.info("=" * 60)
    logger.info(f"Current time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")

    scheduler = QuoteSchedulerService(blocking=True)
    scheduler.setup_daily_job(hour=6, minute=0)

    logger.info(f"Next run: {scheduler.get_next_run_time()}")
    logger.info("Scheduler is running. Press Ctrl+C to stop.")
    logger.info("=" * 60)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user")
        scheduler.stop()


# Singleton instance for background scheduler
_scheduler_service = None


def get_scheduler_service() -> QuoteSchedulerService:
    """Get the singleton instance of the scheduler service (background mode)."""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = QuoteSchedulerService(blocking=False)
    return _scheduler_service


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auto Quote Poster Scheduler")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run quote generation immediately instead of scheduling"
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=6,
        help="Hour to schedule (0-23 in IST, default: 6)"
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=0,
        help="Minute to schedule (0-59, default: 0)"
    )

    args = parser.parse_args()

    if args.run_now:
        logger.info("Running quote generation immediately...")
        success = generate_and_post_quote()
        if success:
            logger.info("Quote posted successfully!")
        else:
            logger.error("Failed to post quote")
    else:
        # Run as daemon with custom time
        logger.info("=" * 60)
        logger.info("AUTO QUOTE POSTER SCHEDULER")
        logger.info("=" * 60)
        logger.info(f"Current time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")

        scheduler = QuoteSchedulerService(blocking=True)
        scheduler.setup_daily_job(hour=args.hour, minute=args.minute)

        logger.info(f"Next run: {scheduler.get_next_run_time()}")
        logger.info("Scheduler is running. Press Ctrl+C to stop.")
        logger.info("=" * 60)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped by user")
