"""
Quote Generator Service for Auto Quote Poster.

This service handles:
- Retrieving random chunks from the vector store
- Using OpenAI to generate inspiring quotes from content
- Formatting quotes with saying and description
"""

import os
import random
from datetime import datetime
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

from vector_store_service import get_vector_store_service
from llm_usage_tracker import record_openai_response

load_dotenv()


class QuoteGeneratorService:
    """Service for generating quotes from vector store content."""

    def __init__(self):
        """Initialize the quote generator service."""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.vector_store = get_vector_store_service()
        self.model = "gpt-4o-mini"

    def generate_quote_from_chunks(self, num_chunks: int = 3) -> Optional[dict]:
        """
        Generate a quote by retrieving random chunks and using AI.

        Args:
            num_chunks: Number of random chunks to use as context

        Returns:
            Dictionary with quote, saying, description, and metadata
        """
        # Get random chunks from vector store
        chunks = self.vector_store.get_random_chunks(num_chunks)

        if not chunks:
            print("[WARNING] No chunks available in vector store")
            return None

        # Combine chunk contents
        context = "\n\n---\n\n".join([chunk['content'] for chunk in chunks])

        # Generate quote using OpenAI
        prompt = f"""Based on the following content, create an inspiring and profound quote.
The quote should be original, memorable, and capture the essence of wisdom from the content.

Content:
{context}

Generate a response in the following JSON format:
{{
    "quote": "The main quote text - should be 1-3 sentences, inspiring and memorable",
    "saying": "A short 2-5 word tagline or theme (e.g., 'Inner Peace', 'Mindful Living')",
    "description": "A 1-2 sentence description explaining the context or meaning of the quote"
}}

Important:
- The quote should feel authentic and inspiring
- It should be suitable for a meditation/mindfulness app
- The saying should be concise and capture the theme
- The description should add value without being too long

Return ONLY the JSON, no other text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a wise spiritual teacher who creates profound, inspiring quotes. Your quotes blend ancient wisdom with modern understanding."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.8,
                max_tokens=500
            )
            record_openai_response(response, service="quote_generator")

            # Parse the response
            content = response.choices[0].message.content.strip()

            # Clean up JSON if wrapped in markdown
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            import json
            quote_data = json.loads(content)

            # Add metadata
            quote_data['generated_at'] = datetime.now().isoformat()
            quote_data['source_chunks'] = [
                {
                    'content_preview': chunk['content'][:100] + '...',
                    'source_url': chunk['metadata'].get('source_url', 'unknown')
                }
                for chunk in chunks
            ]

            print(f"[SUCCESS] Generated quote: {quote_data['quote'][:50]}...")
            return quote_data

        except Exception as e:
            print(f"[ERROR] Failed to generate quote: {e}")
            return None

    def generate_themed_quote(self, theme: str, num_chunks: int = 3) -> Optional[dict]:
        """
        Generate a quote based on a specific theme using similar chunks.

        Args:
            theme: The theme to search for (e.g., "meditation", "peace")
            num_chunks: Number of similar chunks to use

        Returns:
            Dictionary with quote, saying, description, and metadata
        """
        # Search for chunks similar to the theme
        chunks = self.vector_store.search_similar(theme, k=num_chunks)

        if not chunks:
            print(f"[WARNING] No chunks found for theme: {theme}")
            return None

        # Combine chunk contents
        context = "\n\n---\n\n".join([chunk['content'] for chunk in chunks])

        # Generate quote using OpenAI
        prompt = f"""Based on the following content about "{theme}", create an inspiring and profound quote.
The quote should be original, memorable, and capture the essence of {theme}.

Content:
{context}

Generate a response in the following JSON format:
{{
    "quote": "The main quote text - should be 1-3 sentences, inspiring and memorable",
    "saying": "A short 2-5 word tagline or theme",
    "description": "A 1-2 sentence description explaining the context or meaning of the quote"
}}

Important:
- The quote should feel authentic and deeply inspiring
- It should relate to {theme}
- It should be suitable for a meditation/mindfulness app
- The saying should be concise and capture the essence

Return ONLY the JSON, no other text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a wise spiritual teacher who creates profound, inspiring quotes. Your quotes blend ancient wisdom with modern understanding."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.8,
                max_tokens=500
            )
            record_openai_response(response, service="quote_generator")

            # Parse the response
            content = response.choices[0].message.content.strip()

            # Clean up JSON if wrapped in markdown
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            import json
            quote_data = json.loads(content)

            # Add metadata
            quote_data['theme'] = theme
            quote_data['generated_at'] = datetime.now().isoformat()
            quote_data['source_chunks'] = [
                {
                    'content_preview': chunk['content'][:100] + '...',
                    'source_url': chunk['metadata'].get('source_url', 'unknown'),
                    'similarity_score': chunk.get('score', 0)
                }
                for chunk in chunks
            ]

            print(f"[SUCCESS] Generated themed quote: {quote_data['quote'][:50]}...")
            return quote_data

        except Exception as e:
            print(f"[ERROR] Failed to generate themed quote: {e}")
            return None

    def generate_multiple_quotes(self, count: int = 5) -> list[dict]:
        """
        Generate multiple unique quotes.

        Args:
            count: Number of quotes to generate

        Returns:
            List of quote dictionaries
        """
        quotes = []
        attempts = 0
        max_attempts = count * 2  # Allow some failures

        while len(quotes) < count and attempts < max_attempts:
            attempts += 1
            quote = self.generate_quote_from_chunks()

            if quote:
                # Check for duplicates
                is_duplicate = any(
                    q['quote'].lower() == quote['quote'].lower()
                    for q in quotes
                )

                if not is_duplicate:
                    quotes.append(quote)
                    print(f"[INFO] Generated {len(quotes)}/{count} quotes")

        return quotes


# Singleton instance
_generator_service = None


def get_quote_generator_service() -> QuoteGeneratorService:
    """Get the singleton instance of the quote generator service."""
    global _generator_service
    if _generator_service is None:
        _generator_service = QuoteGeneratorService()
    return _generator_service


if __name__ == "__main__":
    # Quick test
    service = get_quote_generator_service()

    # Check if vector store has content
    vs = get_vector_store_service()
    stats = vs.get_stats()
    print(f"Vector Store Stats: {stats}")

    if stats['total_chunks'] > 0:
        # Generate a random quote
        print("\nGenerating random quote...")
        quote = service.generate_quote_from_chunks()
        if quote:
            print(f"\nQuote: {quote['quote']}")
            print(f"Saying: {quote['saying']}")
            print(f"Description: {quote['description']}")
    else:
        print("\n[INFO] Vector store is empty. Index some content first!")
        print("Use webpage_scraper_service.py to scrape and index content.")
