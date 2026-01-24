"""Vector store for topic deduplication using Qdrant and Gemini embeddings."""

import logging
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from src.core.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "mandarin_topics"
EMBEDDING_DIMENSIONS = 768  # text-embedding-004 output size


class TopicVectorStore:
    """Qdrant-backed vector store for detecting similar topic contexts."""

    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None
        self._collection_ensured = False

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(url=settings.qdrant_url)
        return self._client

    async def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        if self._collection_ensured:
            return

        client = self._get_client()
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]

        if COLLECTION_NAME not in existing:
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMENSIONS,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection: {COLLECTION_NAME}")

        self._collection_ensured = True

    async def _embed(self, text: str) -> list[float]:
        """Embed text using Gemini text-embedding-004."""
        from src.llm.key_rotator import gemini_key_rotator

        client = gemini_key_rotator.get_client()
        result = await client.aio.models.embed_content(
            model=settings.gemini_embedding_model,
            contents=text,
        )
        return list(result.embeddings[0].values)

    async def is_similar(self, text: str) -> tuple[bool, float]:
        """
        Check if text is semantically similar to any stored topic context.

        Args:
            text: The web content to check

        Returns:
            Tuple of (is_similar, highest_score). Score is 0.0 if no matches found.
        """
        try:
            await self._ensure_collection()
            embedding = await self._embed(text)

            client = self._get_client()
            results = await client.query_points(
                collection_name=COLLECTION_NAME,
                query=embedding,
                limit=1,
            )

            if not results.points:
                return False, 0.0

            score = results.points[0].score
            is_similar = score >= settings.topic_similarity_threshold
            logger.info(
                f"Similarity check: score={score:.4f}, "
                f"threshold={settings.topic_similarity_threshold}, "
                f"similar={is_similar}"
            )
            return is_similar, score

        except Exception as e:
            logger.warning(f"Qdrant similarity check failed: {e}. Proceeding without check.")
            return False, 0.0

    async def store(self, text: str, metadata: dict) -> None:
        """
        Embed and store topic context in Qdrant.

        Args:
            text: The web content used for generation
            metadata: Dict with keys like topic, date, source_url
        """
        try:
            await self._ensure_collection()
            embedding = await self._embed(text)

            client = self._get_client()
            point_id = str(uuid.uuid4())
            await client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=metadata,
                    )
                ],
            )
            logger.info(f"Stored new topic embedding: {metadata.get('topic', 'unknown')}")

        except Exception as e:
            logger.warning(f"Failed to store topic embedding: {e}. Continuing without storage.")


topic_vector_store = TopicVectorStore()
