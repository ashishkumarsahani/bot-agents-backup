"""
Auto Quote Poster Service - Main Orchestrator

This is the main entry point for the Auto Quote Poster service.
It provides a CLI interface to:
- Manage webpage URLs and indexing
- Generate quotes from indexed content
- Post quotes to Firestore
- Run the scheduler for daily automated posting

Usage:
    python auto_quote_service.py [command]

Commands:
    index       - Index webpages from managed URLs
    generate    - Generate a quote from indexed content
    post        - Generate and post a quote to Firestore
    schedule    - Start the scheduler daemon (runs at 6 AM IST)
    stats       - Show statistics
    streamlit   - Launch the Streamlit web interface
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Import all services
from vector_store_service import get_vector_store_service
from webpage_scraper_service import get_webpage_scraper_service
from quote_generator_service import get_quote_generator_service
from firestore_service import get_firestore_service
from scheduler_service import generate_and_post_quote, run_scheduler_daemon

# Configuration
URLS_FILE = Path(__file__).parent / "managed_urls.json"
IST = ZoneInfo("Asia/Kolkata")


def load_urls() -> list[dict]:
    """Load managed URLs from file."""
    if URLS_FILE.exists():
        with open(URLS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_urls(urls: list[dict]):
    """Save managed URLs to file."""
    with open(URLS_FILE, 'w') as f:
        json.dump(urls, f, indent=2)


def cmd_add_url(args):
    """Add a new URL to the managed list."""
    urls = load_urls()

    # Check for duplicates
    existing = [u['url'] for u in urls]
    if args.url in existing:
        print(f"[ERROR] URL already exists: {args.url}")
        return False

    new_entry = {
        "url": args.url,
        "title": args.title or "Untitled",
        "category": args.category,
        "added_at": datetime.now().isoformat(),
        "indexed": False
    }

    urls.append(new_entry)
    save_urls(urls)

    print(f"[SUCCESS] Added URL: {args.url}")
    print(f"          Title: {new_entry['title']}")
    print(f"          Category: {args.category}")

    if args.index:
        print("\nIndexing content...")
        cmd_index(None)

    return True


def cmd_list_urls(args):
    """List all managed URLs."""
    urls = load_urls()

    if not urls:
        print("[INFO] No URLs managed. Use 'add-url' to add some.")
        return

    print(f"\n{'='*60}")
    print(f"MANAGED URLS ({len(urls)})")
    print(f"{'='*60}\n")

    for i, url in enumerate(urls, 1):
        status = "Indexed" if url.get('indexed') else "Pending"
        print(f"{i}. {url.get('title', 'Untitled')}")
        print(f"   URL: {url['url']}")
        print(f"   Category: {url.get('category', 'N/A')}")
        print(f"   Status: {status}")
        if url.get('chunks'):
            print(f"   Chunks: {url['chunks']}")
        print()


def cmd_index(args):
    """Index all unindexed URLs."""
    urls = load_urls()
    unindexed = [u for u in urls if not u.get('indexed')]

    if not unindexed:
        print("[INFO] All URLs are already indexed!")
        return

    print(f"\n{'='*60}")
    print(f"INDEXING {len(unindexed)} URLs")
    print(f"{'='*60}\n")

    scraper = get_webpage_scraper_service()

    for i, url_data in enumerate(unindexed, 1):
        print(f"[{i}/{len(unindexed)}] {url_data['url']}")

        result = scraper.scrape_and_index(
            url_data['url'],
            metadata={
                "category": url_data.get('category'),
                "title": url_data.get('title')
            }
        )

        if result['success']:
            url_data['indexed'] = True
            url_data['chunks'] = result.get('chunks_added', 0)
            print(f"    [SUCCESS] {result['chunks_added']} chunks indexed\n")
        else:
            print(f"    [FAILED] {result.get('error', 'Unknown error')}\n")

    save_urls(urls)

    print(f"\n{'='*60}")
    print("INDEXING COMPLETE")
    print(f"{'='*60}")


def cmd_generate(args):
    """Generate a quote from indexed content."""
    vs = get_vector_store_service()
    stats = vs.get_stats()

    if stats.get('total_chunks', 0) == 0:
        print("[ERROR] Vector store is empty. Index some content first!")
        return None

    generator = get_quote_generator_service()

    if args.theme:
        print(f"\nGenerating themed quote about '{args.theme}'...")
        quote = generator.generate_themed_quote(args.theme)
    else:
        print("\nGenerating random quote...")
        quote = generator.generate_quote_from_chunks()

    if quote:
        print(f"\n{'='*60}")
        print("GENERATED QUOTE")
        print(f"{'='*60}\n")
        print(f'"{quote["quote"]}"')
        print(f"\nSaying: {quote['saying']}")
        print(f"Description: {quote['description']}")
        print()
        return quote
    else:
        print("[ERROR] Failed to generate quote")
        return None


def cmd_post(args):
    """Generate and post a quote to Firestore."""
    print(f"\n{'='*60}")
    print("GENERATE AND POST QUOTE")
    print(f"{'='*60}")
    print(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")

    success = generate_and_post_quote()

    if success:
        print("\n[SUCCESS] Quote generated and posted to Firestore!")
    else:
        print("\n[ERROR] Failed to generate or post quote")

    return success


def cmd_schedule(args):
    """Start the scheduler daemon."""
    print(f"\n{'='*60}")
    print("STARTING SCHEDULER DAEMON")
    print(f"{'='*60}")
    print(f"Schedule: {args.hour:02d}:{args.minute:02d} IST daily")
    print("Press Ctrl+C to stop\n")

    run_scheduler_daemon()


def cmd_stats(args):
    """Show statistics."""
    print(f"\n{'='*60}")
    print("AUTO QUOTE POSTER STATISTICS")
    print(f"{'='*60}\n")

    # Vector store stats
    vs = get_vector_store_service()
    vs_stats = vs.get_stats()

    print("Vector Store:")
    print(f"  Total Chunks: {vs_stats.get('total_chunks', 0)}")
    print(f"  Total Sources: {vs_stats.get('total_sources', 0)}")

    # URL stats
    urls = load_urls()
    indexed = sum(1 for u in urls if u.get('indexed'))

    print(f"\nManaged URLs:")
    print(f"  Total: {len(urls)}")
    print(f"  Indexed: {indexed}")
    print(f"  Pending: {len(urls) - indexed}")

    # Firestore stats
    firestore = get_firestore_service()
    if firestore.is_connected():
        count = firestore.get_quote_count()
        print(f"\nFirestore:")
        print(f"  Total Quotes: {count}")
        print(f"  Status: Connected")
    else:
        print(f"\nFirestore:")
        print(f"  Status: Not connected")


def cmd_streamlit(args):
    """Launch the Streamlit web interface."""
    import subprocess
    import os

    script_dir = Path(__file__).parent
    streamlit_app = script_dir / "streamlit_app.py"

    print(f"\n{'='*60}")
    print("LAUNCHING STREAMLIT WEB INTERFACE")
    print(f"{'='*60}\n")
    print("Starting server at http://localhost:8501")
    print("Press Ctrl+C to stop\n")

    os.chdir(script_dir)
    subprocess.run(["streamlit", "run", str(streamlit_app)])


def main():
    parser = argparse.ArgumentParser(
        description="Auto Quote Poster Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auto_quote_service.py add-url https://example.com/article --title "My Article"
  python auto_quote_service.py list-urls
  python auto_quote_service.py index
  python auto_quote_service.py generate
  python auto_quote_service.py generate --theme meditation
  python auto_quote_service.py post
  python auto_quote_service.py schedule
  python auto_quote_service.py stats
  python auto_quote_service.py streamlit
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add URL command
    add_parser = subparsers.add_parser("add-url", help="Add a new URL to manage")
    add_parser.add_argument("url", help="The webpage URL to add")
    add_parser.add_argument("--title", "-t", help="Title or description")
    add_parser.add_argument(
        "--category", "-c",
        default="mindfulness",
        choices=["mindfulness", "meditation", "yoga", "spirituality", "motivation", "wisdom"],
        help="Content category"
    )
    add_parser.add_argument("--index", "-i", action="store_true", help="Index immediately after adding")

    # List URLs command
    subparsers.add_parser("list-urls", help="List all managed URLs")

    # Index command
    subparsers.add_parser("index", help="Index all unindexed URLs")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate a quote")
    gen_parser.add_argument("--theme", "-t", help="Generate themed quote")

    # Post command
    subparsers.add_parser("post", help="Generate and post a quote to Firestore")

    # Schedule command
    sched_parser = subparsers.add_parser("schedule", help="Start the scheduler daemon")
    sched_parser.add_argument("--hour", type=int, default=6, help="Hour to run (IST, default: 6)")
    sched_parser.add_argument("--minute", type=int, default=0, help="Minute to run (default: 0)")

    # Stats command
    subparsers.add_parser("stats", help="Show statistics")

    # Streamlit command
    subparsers.add_parser("streamlit", help="Launch web interface")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Execute command
    if args.command == "add-url":
        cmd_add_url(args)
    elif args.command == "list-urls":
        cmd_list_urls(args)
    elif args.command == "index":
        cmd_index(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "post":
        cmd_post(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "streamlit":
        cmd_streamlit(args)


if __name__ == "__main__":
    main()
