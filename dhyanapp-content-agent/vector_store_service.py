"""
ChromaDB Vector Store Service for Auto Quote Poster.

This service handles:
- Storing webpage content as chunked embeddings
- Retrieving random chunks for quote generation
- Managing the vector database lifecycle
"""

import os
import random
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

load_dotenv()

# ChromaDB storage path
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
COLLECTION_NAME = "quote_sources"


class VectorStoreService:
    """Service for managing ChromaDB vector store for quote sources."""

    def __init__(self):
        """Initialize the vector store service."""
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

        # Initialize ChromaDB client with persistent storage
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

        # Initialize Langchain Chroma wrapper
        self.vectorstore = Chroma(
            client=self.client,
            collection_name=COLLECTION_NAME,
            embedding_function=self.embeddings,
            persist_directory=CHROMA_PERSIST_DIR
        )

        # Text splitter for chunking content
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def add_content(self, content: str, source_url: str, metadata: Optional[dict] = None) -> int:
        """
        Add content to the vector store after chunking.

        Args:
            content: The text content to store
            source_url: URL where the content was scraped from
            metadata: Optional additional metadata

        Returns:
            Number of chunks added
        """
        if not content or not content.strip():
            print(f"[WARNING] Empty content for URL: {source_url}")
            return 0

        # Split content into chunks
        chunks = self.text_splitter.split_text(content)

        if not chunks:
            print(f"[WARNING] No chunks created for URL: {source_url}")
            return 0

        # Prepare metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = {
                "source_url": source_url,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "indexed_at": datetime.now().isoformat(),
            }
            if metadata:
                chunk_metadata.update(metadata)
            metadatas.append(chunk_metadata)

        # Add to vector store
        self.vectorstore.add_texts(texts=chunks, metadatas=metadatas)

        print(f"[SUCCESS] Added {len(chunks)} chunks from {source_url}")
        return len(chunks)

    def get_random_chunks(self, n: int = 5) -> list[dict]:
        """
        Retrieve random chunks from the vector store.

        Args:
            n: Number of random chunks to retrieve

        Returns:
            List of dicts with 'content' and 'metadata' keys
        """
        # Get the collection directly to access all documents
        collection = self.client.get_collection(COLLECTION_NAME)

        # Get all documents
        all_docs = collection.get(include=["documents", "metadatas"])

        documents = all_docs.get("documents") or []
        if not documents:
            print("[WARNING] No documents in vector store")
            return []

        metadatas = all_docs.get("metadatas") or [{} for _ in documents]

        # Select random indices
        total_docs = len(documents)
        n = min(n, total_docs)
        random_indices = random.sample(range(total_docs), n)

        # Build result
        result = []
        for idx in random_indices:
            result.append({
                "content": documents[idx],
                "metadata": metadatas[idx] if idx < len(metadatas) else {}
            })

        return result

    def search_similar(self, query: str, k: int = 5) -> list[dict]:
        """
        Search for chunks similar to the query.

        Args:
            query: Search query
            k: Number of results to return

        Returns:
            List of similar chunks with metadata
        """
        results = self.vectorstore.similarity_search_with_score(query, k=k)

        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": score
            }
            for doc, score in results
        ]

    def get_all_sources(self) -> list[str]:
        """Get all unique source URLs in the vector store."""
        collection = self.client.get_collection(COLLECTION_NAME)
        all_docs = collection.get(include=["metadatas"])

        metadatas = all_docs.get("metadatas") or []
        if not metadatas:
            return []

        sources = set()
        for metadata in metadatas:
            if metadata and "source_url" in metadata:
                sources.add(metadata["source_url"])

        return list(sources)

    def get_stats(self) -> dict:
        """Get statistics about the vector store."""
        collection = self.client.get_collection(COLLECTION_NAME)
        total_chunks = collection.count()
        sources = self.get_all_sources()

        return {
            "total_chunks": total_chunks,
            "total_sources": len(sources),
            "sources": sources
        }

    def delete_source(self, source_url: str) -> bool:
        """
        Delete all chunks from a specific source URL.

        Args:
            source_url: The URL to remove

        Returns:
            True if deletion was successful
        """
        collection = self.client.get_collection(COLLECTION_NAME)

        # Get all documents to find IDs to delete
        all_docs = collection.get(include=["metadatas"])

        ids_to_delete = []
        for i, metadata in enumerate(all_docs.get("metadatas", [])):
            if metadata and metadata.get("source_url") == source_url:
                ids_to_delete.append(all_docs["ids"][i])

        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            print(f"[SUCCESS] Deleted {len(ids_to_delete)} chunks from {source_url}")
            return True

        print(f"[WARNING] No chunks found for {source_url}")
        return False

    def clear_all(self) -> bool:
        """Clear all data from the vector store."""
        try:
            self.client.delete_collection(COLLECTION_NAME)
            # Recreate collection
            self.vectorstore = Chroma(
                client=self.client,
                collection_name=COLLECTION_NAME,
                embedding_function=self.embeddings,
                persist_directory=CHROMA_PERSIST_DIR
            )
            print("[SUCCESS] Cleared all data from vector store")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to clear vector store: {e}")
            return False


# Singleton instance
_vector_store_service = None


def get_vector_store_service() -> VectorStoreService:
    """Get the singleton instance of the vector store service."""
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service


if __name__ == "__main__":
    # Quick test
    service = get_vector_store_service()

    # Add some test content
    test_content = """
    Mindfulness is the practice of being present in the moment.
    When we are mindful, we observe our thoughts without judgment.
    The breath is an anchor that brings us back to the present.
    Meditation helps cultivate inner peace and clarity.
    Through regular practice, we develop greater awareness.
    """

    service.add_content(
        content=test_content,
        source_url="https://example.com/mindfulness-article",
        metadata={"category": "mindfulness", "title": "Test Article"}
    )

    print("\nStats:", service.get_stats())

    print("\nRandom chunks:")
    for chunk in service.get_random_chunks(3):
        print(f"- {chunk['content'][:100]}...")
