"""Read-only historical comment acquisition for private Shadow evidence."""

from app.acquisition.common import (
    AcquiredComment,
    AcquisitionBatch,
    AcquisitionLimitExceeded,
    AcquisitionProtocolError,
    write_replay_jsonl,
)

__all__ = [
    "AcquiredComment",
    "AcquisitionBatch",
    "AcquisitionLimitExceeded",
    "AcquisitionProtocolError",
    "write_replay_jsonl",
]
