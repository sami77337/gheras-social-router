from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from app.acquisition.common import write_replay_jsonl
from app.integrations.live.historical_meta import MetaHistoricalCommentClient
from app.integrations.live.activation import issue_sandbox_execution_permit


async def _run(
    *,
    platform: str,
    source_ids: list[str],
    output: Path,
    access_token: str,
    api_version: str,
) -> None:
    permit = issue_sandbox_execution_permit(purpose="sandbox_validation")
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = MetaHistoricalCommentClient(
            http=http,
            permit=permit,
            access_token=access_token,
            api_version=api_version,
        )
        if platform == "facebook":
            batch = await client.collect_facebook_posts(source_ids)
        else:
            batch = await client.collect_instagram_media(source_ids)

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
        description="Read Meta comments into private Gheras replay JSONL."
    )
    parser.add_argument("--platform", choices=("facebook", "instagram"), required=True)
    parser.add_argument("--source-id", action="append", required=True)
    parser.add_argument("--api-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-read-only-provider-call",
        action="store_true",
        help="Required explicit acknowledgement before any Graph API GET request.",
    )
    args = parser.parse_args()
    if not args.confirm_read_only_provider_call:
        parser.error("--confirm-read-only-provider-call is required")

    access_token = os.environ.get("GHERAS_META_ACCESS_TOKEN")
    if not access_token:
        raise SystemExit("GHERAS_META_ACCESS_TOKEN is not configured")
    asyncio.run(
        _run(
            platform=args.platform,
            source_ids=args.source_id,
            output=args.output,
            access_token=access_token,
            api_version=args.api_version,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
