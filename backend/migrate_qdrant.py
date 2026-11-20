
import os
import sys

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

import service.qdrant_service as qdrant_service


load_dotenv()

SOURCE_COLLECTION = "note_chunks"
TARGET_COLLECTION = "note_chunks_gemini_768"

BATCH_SIZE = 50


def migrate():

    print("Starting Qdrant migration...")

    # Initialize the new collection and Gemini embedding client.
    qdrant_service.initialize_qdrant()

    source_url = os.getenv("QDRANT_URL")
    source_api_key = os.getenv("QDRANT_API_KEY")

    if not source_url or not source_api_key:
        raise RuntimeError("Qdrant credentials are missing")

    source_client = QdrantClient(
        url=source_url,
        api_key=source_api_key,
        timeout=60
    )

    target_client = qdrant_service.client

    if not source_client.collection_exists(SOURCE_COLLECTION):
        raise RuntimeError(
            f"Source collection '{SOURCE_COLLECTION}' does not exist"
        )

    source_count = source_client.count(
        collection_name=SOURCE_COLLECTION,
        exact=True
    ).count

    target_before = target_client.count(
        collection_name=TARGET_COLLECTION,
        exact=True
    ).count

    print(f"Existing source points: {source_count}")
    print(f"Existing target points: {target_before}")

    if source_count == 0:
        print("Source collection is empty. Nothing to migrate.")
        return

    migrated_count = 0
    next_offset = None

    while True:

        points, next_offset = source_client.scroll(
            collection_name=SOURCE_COLLECTION,
            limit=BATCH_SIZE,
            offset=next_offset,
            with_payload=True,
            with_vectors=False
        )

        if not points:
            break

        texts = []
        payloads = []
        point_ids = []

        for point in points:

            payload = point.payload or {}

            # Support both current and older payload field names.
            content = (
                payload.get("content")
                or payload.get("document")
            )

            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(
                    f"Point {point.id} has no usable text content. "
                    "Migration stopped to avoid silently losing data."
                )

            texts.append(content)
            payloads.append(payload)
            point_ids.append(point.id)

        # Generate new Gemini embeddings.
        vectors = qdrant_service.generate_embeddings(
            texts,
            task_type="RETRIEVAL_DOCUMENT"
        )

        new_points = []

        for point_id, payload, vector in zip(
            point_ids,
            payloads,
            vectors
        ):

            new_points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )
            )

        # Preserve original point IDs and payloads.
        target_client.upsert(
            collection_name=TARGET_COLLECTION,
            points=new_points,
            wait=True
        )

        migrated_count += len(new_points)

        print(
            f"Migrated {migrated_count}/{source_count} points"
        )

        if next_offset is None:
            break

    target_after = target_client.count(
        collection_name=TARGET_COLLECTION,
        exact=True
    ).count

    print("\nMigration finished.")
    print(f"Source points: {source_count}")
    print(f"Points processed: {migrated_count}")
    print(f"Target points before: {target_before}")
    print(f"Target points after: {target_after}")

    if migrated_count != source_count:
        raise RuntimeError(
            "Migration verification failed: processed count "
            "does not match source count."
        )

    print("\nMigration verification passed.")
    print("Original collection remains untouched.")


if __name__ == "__main__":

    try:
        migrate()

    except Exception as error:
        print(f"\nMigration failed: {error}")
        sys.exit(1)
