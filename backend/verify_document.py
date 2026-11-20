
import service.qdrant_service as qs
from qdrant_client import models

DOCUMENT_ID = "ae694391-d45e-4e28-8d8a-b5ce98648ac1"

CONVERSATION_ID = "5108f8e2-20ee-4b3c-ab8b-752ad7fdf3cc"

qs.initialize_qdrant()

results, next_offset = qs.client.scroll(
    collection_name=qs.COLLECTION_NAME,
    scroll_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=DOCUMENT_ID)
            ),
            models.FieldCondition(
                key="conversation_id",
                match=models.MatchValue(value=CONVERSATION_ID)
            ),
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value="document")
            )
        ]
    ),
    limit=100,
    with_payload=True,
    with_vectors=False
)

print("\n========== DOCUMENT VERIFICATION ==========")

print("Expected chunks: 3")
print("Actual chunks:", len(results))

for point in results:
    payload = point.payload or {}

    print("\nPoint ID:", point.id)
    print("Document ID:", payload.get("document_id"))
    print("Conversation ID:", payload.get("conversation_id"))
    print("Filename:", payload.get("filename"))
    print("Chunk index:", payload.get("chunk_index"))
    print("Content preview:", payload.get("content", "")[:100])

print("\n========== RESULT ==========")

if len(results) == 3:
    print("SUCCESS: All 3 chunks found.")
else:
    print("CHECK REQUIRED: Expected 3 chunks.")

print("============================================")
