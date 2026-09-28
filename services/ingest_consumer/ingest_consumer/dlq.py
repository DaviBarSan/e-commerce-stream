"""Dead-letter message envelope (spec 04 §9)."""
import base64
import json
from datetime import datetime, timezone


def dlq_envelope(*, error: str, topic: str, partition: int, offset: int, original: bytes | None) -> bytes:
    """The DLQ message: why it failed, where it came from, and the original bytes (base64, so any bytes survive)."""
    return json.dumps({
        "error": error,
        "source_topic": topic,
        "source_partition": partition,
        "source_offset": offset,
        "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "consumer": "ingest_consumer",
        "original_payload_b64": base64.b64encode(original or b"").decode("ascii"),
    }).encode("utf-8")
