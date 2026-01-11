"""
Webpage Scraper Service for Auto Quote Poster.

This service handles:
- Scraping webpage content using Serper API (scraping endpoint)
- Fallback to direct HTTP requests with BeautifulSoup
- Extracting clean text content from HTML
- Integrating with the vector store for indexing
"""

import os
import re
import requests
from typing import Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from vector_store_service import get_vector_store_service

load_dotenv()

# Serper API configuration
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "0b782bd4e358b2b11b4fbc9ec890c71792aab682")
SERPER_SCRAPE_URL = "https://scrape.serper.dev"


class WebpageScraperService:
    """Service for scraping webpages and indexing content to vector store."""

    def __init__(self):
        """Initialize the webpage scraper service."""
        self.vector_store = get_vector_store_service()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def scrape_with_serper(self, url: str) -> Optional[str]:
        """
        Scrape webpage content using Serper API.

        Args:
            url: The webpage URL to scrape

        Returns:
            Cleaned text content or None if failed
        """
        print(f"[INFO] Scraping with Serper: {url}")

        headers = {
            'X-API-KEY': SERPER_API_KEY,
            'Content-Type': 'application/json'
        }

        payload = {
            'url': url
        }

        try:
            response = requests.post(
                SERPER_SCRAPE_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            # Serper returns text content in the response
            text_content = data.get('text', '')

            if text_content:
                print(f"[SUCCESS] Serper scraped {len(text_content)} characters")
                return self._clean_text(text_content)

            # Fallback to HTML parsing if text not available
            html_content = data.get('html', '')
            if html_content:
                return self._extract_text_from_html(html_content)

            print("[WARNING] No content from Serper response")
            return None

        except requests.exceptions.HTTPError as e:
            print(f"[WARNING] Serper API error: {e}")
            return None
        except Exception as e:
            print(f"[ERROR] Serper scraping failed: {e}")
            return None

    def scrape_with_requests(self, url: str) -> Optional[str]:
        """
        Scrape webpage content using direct HTTP request.

        Args:
            url: The webpage URL to scrape

        Returns:
            Cleaned text content or None if failed
        """
        print(f"[INFO] Scraping with requests: {url}")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get('content-type', '')
            if 'text/html' not in content_type.lower():
                print(f"[WARNING] Not HTML content: {content_type}")
                return None

            html_content = response.text
            text_content = self._extract_text_from_html(html_content)

            if text_content:
                print(f"[SUCCESS] Scraped {len(text_content)} characters")
                return text_content

            return None

        except Exception as e:
            print(f"[ERROR] Direct scraping failed: {e}")
            return None

    def _extract_text_from_html(self, html: str) -> str:
        """
        Extract clean text from HTML content.

        Args:
            html: Raw HTML content

        Returns:
            Cleaned text content
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer',
                            'aside', 'form', 'noscript', 'iframe']):
            element.decompose()

        # Get text from main content areas
        main_content = None

        # Try to find main content area
        for selector in ['main', 'article', '[role="main"]', '.content',
                        '#content', '.post-content', '.entry-content']:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # If no main content found, use body
        if not main_content:
            main_content = soup.body if soup.body else soup

        # Extract text
        text = main_content.get_text(separator='\n', strip=True)

        return self._clean_text(text)

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text content.

        Args:
            text: Raw text content

        Returns:
            Cleaned text
        """
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        # Remove common noise patterns
        noise_patterns = [
            r'Subscribe to our newsletter.*?(?=\n|$)',
            r'Follow us on.*?(?=\n|$)',
            r'Share this.*?(?=\n|$)',
            r'Cookie.*?(?=\n|$)',
            r'Privacy Policy.*?(?=\n|$)',
            r'Terms of Service.*?(?=\n|$)',
            r'All rights reserved.*?(?=\n|$)',
        ]

        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Strip and return
        return text.strip()

    def scrape_and_index(self, url: str, metadata: Optional[dict] = None) -> dict:
        """
        Scrape a webpage and index its content to the vector store.

        Args:
            url: The webpage URL to scrape
            metadata: Optional metadata to store with the content

        Returns:
            Dictionary with scraping results
        """
        print(f"\n{'='*60}")
        print(f"SCRAPING AND INDEXING: {url}")
        print(f"{'='*60}\n")

        # Try Serper first, fallback to direct requests
        content = self.scrape_with_serper(url)

        if not content:
            print("[INFO] Falling back to direct HTTP request...")
            content = self.scrape_with_requests(url)

        if not content:
            return {
                'success': False,
                'url': url,
                'error': 'Failed to scrape content',
                'chunks_added': 0
            }

        # Index to vector store
        chunks_added = self.vector_store.add_content(
            content=content,
            source_url=url,
            metadata=metadata
        )

        return {
            'success': True,
            'url': url,
            'content_length': len(content),
            'chunks_added': chunks_added
        }

    def scrape_multiple(self, urls: list[dict]) -> dict:
        """
        Scrape multiple webpages and index their content.

        Args:
            urls: List of dictionaries with 'url' and optional 'metadata' keys

        Returns:
            Summary of scraping results
        """
        results = {
            'total': len(urls),
            'successful': 0,
            'failed': 0,
            'total_chunks': 0,
            'details': []
        }

        for i, url_data in enumerate(urls, 1):
            url = url_data.get('url') if isinstance(url_data, dict) else url_data
            metadata = url_data.get('metadata', {}) if isinstance(url_data, dict) else {}

            print(f"\n[{i}/{len(urls)}] Processing: {url}")

            result = self.scrape_and_index(url, metadata)
            results['details'].append(result)

            if result['success']:
                results['successful'] += 1
                results['total_chunks'] += result.get('chunks_added', 0)
            else:
                results['failed'] += 1

        print(f"\n{'='*60}")
        print("SCRAPING SUMMARY")
        print(f"{'='*60}")
        print(f"Total URLs: {results['total']}")
        print(f"Successful: {results['successful']}")
        print(f"Failed: {results['failed']}")
        print(f"Total Chunks Indexed: {results['total_chunks']}")

        return results


# Singleton instance
_scraper_service = None


def get_webpage_scraper_service() -> WebpageScraperService:
    """Get the singleton instance of the webpage scraper service."""
    global _scraper_service
    if _scraper_service is None:
        _scraper_service = WebpageScraperService()
    return _scraper_service


if __name__ == "__main__":
    # Quick test
    service = get_webpage_scraper_service()

    # Test with a sample URL
    test_urls = [
        {
            "url": "https://www.mindful.org/meditation/mindfulness-getting-started/",
            "metadata": {"category": "mindfulness", "title": "Getting Started with Mindfulness"}
        }
    ]

    results = service.scrape_multiple(test_urls)
    print(f"\nResults: {results}")

    # Show vector store stats
    from vector_store_service import get_vector_store_service
    vs = get_vector_store_service()
    print(f"\nVector Store Stats: {vs.get_stats()}")
