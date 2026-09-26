from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from app.acquisition.common import write_replay_jsonl
from app.integrations.live.activation import issue_sandbox_execution_permit
from app.integrations.live.historical_youtube import YouTubeHistoricalCommentClient


async def _run(channel_id: str, output: Path, api_key: str) -> None:
    permit = issue_sandbox_execution_permit(purpose="sandbox_validation")
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = YouTubeHistoricalCommentClient(
            http=http,
            permit=permit,
            api_key=api_key,
        )
        batch = await client.collect_channel(channel_id)
    replay = write_replay_jsonl(output, batch.comments)
    print(
        json.dumps(
            {
                "acquisition": batch.content_free_manifest(),
                "replay": replay,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read public YouTube comments into private Gheras replay JSONL."
    )
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-read-only-provider-call",
        action="store_true",
        help="Required explicit acknowledgement before any YouTube GET request.",
    )
    args = parser.parse_args()
    if not args.confirm_read_only_provider_call:
        parser.error("--confirm-read-only-provider-call is required")

    api_key = os.environ.get("GHERAS_YOUTUBE_API_KEY")
    if not api_key:
        raise SystemExit("GHERAS_YOUTUBE_API_KEY is not configured")
    asyncio.run(_run(args.channel_id, args.output, api_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
