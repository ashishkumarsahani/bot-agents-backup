"""
Streamlit App for Auto Quote Poster Management.

This app provides a web interface to:
- Manage webpage URLs for content indexing
- View vector store statistics
- Trigger content scraping and indexing
- Generate and preview quotes
- View Firestore quote history
"""

import os
import json
import streamlit as st
from datetime import datetime
from pathlib import Path

# Import services
from vector_store_service import get_vector_store_service
from webpage_scraper_service import get_webpage_scraper_service
from quote_generator_service import get_quote_generator_service
from firestore_service import get_firestore_service

# Configuration
URLS_FILE = Path(__file__).parent / "managed_urls.json"


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


def main():
    st.set_page_config(
        page_title="Auto Quote Poster Manager",
        page_icon="📝",
        layout="wide"
    )

    st.title("Auto Quote Poster Manager")
    st.markdown("Manage your content sources for automatic quote generation and posting.")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["URL Management", "Vector Store", "Quote Generator", "Firestore Quotes"]
    )

    if page == "URL Management":
        url_management_page()
    elif page == "Vector Store":
        vector_store_page()
    elif page == "Quote Generator":
        quote_generator_page()
    elif page == "Firestore Quotes":
        firestore_page()


def url_management_page():
    """Page for managing webpage URLs."""
    st.header("Webpage URL Management")

    # Load existing URLs
    urls = load_urls()

    # Add new URL section
    st.subheader("Add New URL")

    col1, col2 = st.columns([3, 1])

    with col1:
        new_url = st.text_input("Webpage URL", placeholder="https://example.com/article")

    with col2:
        category = st.selectbox(
            "Category",
            ["mindfulness", "meditation", "yoga", "spirituality", "motivation", "wisdom"]
        )

    title = st.text_input("Title (optional)", placeholder="Article title or description")

    if st.button("Add URL", type="primary"):
        if new_url:
            # Check for duplicates
            existing_urls = [u['url'] for u in urls]
            if new_url in existing_urls:
                st.error("This URL already exists!")
            else:
                new_entry = {
                    "url": new_url,
                    "title": title or "Untitled",
                    "category": category,
                    "added_at": datetime.now().isoformat(),
                    "indexed": False
                }
                urls.append(new_entry)
                save_urls(urls)
                st.success(f"Added: {new_url}")
                st.rerun()
        else:
            st.warning("Please enter a URL")

    st.divider()

    # Display existing URLs
    st.subheader(f"Managed URLs ({len(urls)})")

    if not urls:
        st.info("No URLs added yet. Add some URLs above to get started!")
    else:
        # Bulk actions
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Index All Unindexed"):
                scraper = get_webpage_scraper_service()
                unindexed = [u for u in urls if not u.get('indexed')]

                if not unindexed:
                    st.info("All URLs are already indexed!")
                else:
                    progress = st.progress(0)
                    for i, url_data in enumerate(unindexed):
                        result = scraper.scrape_and_index(
                            url_data['url'],
                            metadata={"category": url_data.get('category'), "title": url_data.get('title')}
                        )
                        if result['success']:
                            url_data['indexed'] = True
                            url_data['chunks'] = result.get('chunks_added', 0)
                        progress.progress((i + 1) / len(unindexed))

                    save_urls(urls)
                    st.success(f"Indexed {len(unindexed)} URLs!")
                    st.rerun()

        with col2:
            if st.button("Re-index All"):
                # Clear and re-index
                vs = get_vector_store_service()
                vs.clear_all()

                scraper = get_webpage_scraper_service()
                progress = st.progress(0)

                for i, url_data in enumerate(urls):
                    result = scraper.scrape_and_index(
                        url_data['url'],
                        metadata={"category": url_data.get('category'), "title": url_data.get('title')}
                    )
                    url_data['indexed'] = result['success']
                    url_data['chunks'] = result.get('chunks_added', 0) if result['success'] else 0
                    progress.progress((i + 1) / len(urls))

                save_urls(urls)
                st.success("Re-indexed all URLs!")
                st.rerun()

        with col3:
            if st.button("Clear All URLs", type="secondary"):
                urls = []
                save_urls(urls)
                vs = get_vector_store_service()
                vs.clear_all()
                st.success("Cleared all URLs and vector store!")
                st.rerun()

        st.divider()

        # Display URL table
        for i, url_data in enumerate(urls):
            with st.expander(f"{url_data.get('title', 'Untitled')} - {url_data.get('category', 'N/A')}"):
                st.write(f"**URL:** {url_data['url']}")
                st.write(f"**Added:** {url_data.get('added_at', 'Unknown')}")
                st.write(f"**Indexed:** {'Yes' if url_data.get('indexed') else 'No'}")
                if url_data.get('chunks'):
                    st.write(f"**Chunks:** {url_data['chunks']}")

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("Index", key=f"index_{i}"):
                        scraper = get_webpage_scraper_service()
                        result = scraper.scrape_and_index(
                            url_data['url'],
                            metadata={"category": url_data.get('category'), "title": url_data.get('title')}
                        )
                        if result['success']:
                            url_data['indexed'] = True
                            url_data['chunks'] = result.get('chunks_added', 0)
                            save_urls(urls)
                            st.success("Indexed successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to index. Check logs.")

                with col2:
                    if st.button("Remove from Index", key=f"remove_index_{i}"):
                        vs = get_vector_store_service()
                        vs.delete_source(url_data['url'])
                        url_data['indexed'] = False
                        url_data['chunks'] = 0
                        save_urls(urls)
                        st.success("Removed from index!")
                        st.rerun()

                with col3:
                    if st.button("Delete", key=f"delete_{i}", type="secondary"):
                        vs = get_vector_store_service()
                        vs.delete_source(url_data['url'])
                        urls.pop(i)
                        save_urls(urls)
                        st.success("Deleted!")
                        st.rerun()


def vector_store_page():
    """Page for viewing vector store statistics."""
    st.header("Vector Store Statistics")

    vs = get_vector_store_service()
    stats = vs.get_stats()

    # Display stats
    col1, col2 = st.columns(2)

    with col1:
        st.metric("Total Chunks", stats.get('total_chunks', 0))

    with col2:
        st.metric("Total Sources", stats.get('total_sources', 0))

    st.divider()

    # Source URLs
    st.subheader("Indexed Sources")
    sources = stats.get('sources', [])

    if sources:
        for source in sources:
            st.write(f"- {source}")
    else:
        st.info("No sources indexed yet.")

    st.divider()

    # Sample chunks
    st.subheader("Sample Chunks")

    num_samples = st.slider("Number of samples", 1, 10, 5)

    if st.button("Get Random Samples"):
        chunks = vs.get_random_chunks(num_samples)

        if chunks:
            for i, chunk in enumerate(chunks, 1):
                with st.expander(f"Chunk {i}"):
                    st.write(chunk['content'])
                    st.caption(f"Source: {chunk['metadata'].get('source_url', 'Unknown')}")
        else:
            st.warning("No chunks available. Index some content first!")

    st.divider()

    # Clear vector store
    st.subheader("Danger Zone")
    if st.button("Clear All Data", type="secondary"):
        vs.clear_all()
        st.success("Vector store cleared!")
        st.rerun()


def quote_generator_page():
    """Page for generating and previewing quotes."""
    st.header("Quote Generator")

    generator = get_quote_generator_service()
    vs = get_vector_store_service()
    firestore = get_firestore_service()

    stats = vs.get_stats()

    if stats.get('total_chunks', 0) == 0:
        st.warning("Vector store is empty. Please index some content first!")
        return

    st.info(f"Vector store has {stats['total_chunks']} chunks from {stats['total_sources']} sources.")

    st.divider()

    # Random quote generation
    st.subheader("Generate Random Quote")

    num_chunks = st.slider("Number of context chunks", 1, 10, 3)

    if st.button("Generate Quote", type="primary"):
        with st.spinner("Generating quote..."):
            quote = generator.generate_quote_from_chunks(num_chunks)

            if quote:
                st.success("Quote generated!")

                st.markdown(f"### \"{quote['quote']}\"")
                st.markdown(f"**Saying:** {quote['saying']}")
                st.markdown(f"**Description:** {quote['description']}")

                # Store in session for pushing
                st.session_state['generated_quote'] = quote

                st.divider()

                # Push to Firestore
                if firestore.is_connected():
                    if st.button("Push to Firestore"):
                        doc_id = firestore.push_quote(
                            quote=quote['quote'],
                            saying=quote['saying'],
                            description=quote['description']
                        )
                        if doc_id:
                            st.success(f"Pushed to Firestore! ID: {doc_id}")
                        else:
                            st.error("Failed to push to Firestore")
                else:
                    st.warning("Firestore not connected. Configure Firebase credentials.")
            else:
                st.error("Failed to generate quote. Check your OpenAI API key.")

    st.divider()

    # Themed quote generation
    st.subheader("Generate Themed Quote")

    theme = st.text_input("Theme", placeholder="e.g., meditation, peace, mindfulness")

    if st.button("Generate Themed Quote"):
        if theme:
            with st.spinner(f"Generating quote about '{theme}'..."):
                quote = generator.generate_themed_quote(theme, num_chunks)

                if quote:
                    st.success("Themed quote generated!")

                    st.markdown(f"### \"{quote['quote']}\"")
                    st.markdown(f"**Saying:** {quote['saying']}")
                    st.markdown(f"**Description:** {quote['description']}")
                else:
                    st.error("Failed to generate themed quote.")
        else:
            st.warning("Please enter a theme.")


def firestore_page():
    """Page for viewing Firestore quotes."""
    st.header("Firestore Quotes")

    firestore = get_firestore_service()

    if not firestore.is_connected():
        st.error("Firestore not connected!")
        st.info("Please configure Firebase credentials:")
        st.code("FIREBASE_CREDENTIALS_PATH=path/to/credentials.json", language="bash")
        return

    st.success("Connected to Firestore")

    # Get quote count
    count = firestore.get_quote_count()
    st.metric("Total Quotes", count)

    st.divider()

    # Recent quotes
    st.subheader("Recent Quotes")

    limit = st.slider("Number of quotes to show", 5, 50, 10)

    if st.button("Refresh"):
        st.rerun()

    quotes = firestore.get_recent_quotes(limit)

    if quotes:
        for quote in quotes:
            with st.expander(f"\"{quote.get('quote', 'N/A')[:50]}...\""):
                st.markdown(f"**Quote:** {quote.get('quote', 'N/A')}")
                st.markdown(f"**Saying:** {quote.get('saying', 'N/A')}")
                st.markdown(f"**Description:** {quote.get('description', 'N/A')}")

                created_at = quote.get('createdAt')
                if created_at:
                    st.caption(f"Created: {created_at}")

                if st.button("Delete", key=f"delete_quote_{quote['id']}"):
                    if firestore.delete_quote(quote['id']):
                        st.success("Deleted!")
                        st.rerun()
    else:
        st.info("No quotes in Firestore yet.")


if __name__ == "__main__":
    main()
