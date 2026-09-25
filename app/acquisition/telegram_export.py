"""Local Telegram Desktop HTML-export importer with no network access."""

from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from app.acquisition.common import (
    AcquiredComment,
    AcquisitionBatch,
    AcquisitionLimitExceeded,
    AcquisitionProtocolError,
    bounded_text,
)
from app.domain.events import Platform

_MESSAGE_FILE = re.compile(r"(^|/)messages(?:\d+)?\.html$", re.IGNORECASE)
_MAX_EXPORT_BYTES = 50_000_000
_MAX_MESSAGES = 20_000


class _TelegramHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[tuple[str, str]] = []
        self._div_stack: list[set[str]] = []
        self._message_id: str | None = None
        self._message_depth: int | None = None
        self._service = False
        self._text_depth: int | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "div":
            classes = set((attrs_map.get("class") or "").split())
            self._div_stack.append(classes)
            depth = len(self._div_stack)

            if self._message_depth is None and "message" in classes:
                self._message_depth = depth
                self._message_id = attrs_map.get("id")
                self._service = "service" in classes
                self._text_depth = None
                self._text_parts = []
            elif (
                self._message_depth is not None
                and self._text_depth is None
                and "text" in classes
            ):
                self._text_depth = depth
        elif tag == "br" and self._text_depth is not None:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._div_stack:
            return
        depth = len(self._div_stack)
        if self._text_depth == depth:
            self._text_depth = None
        if self._message_depth == depth:
            if not self._service and self._message_id:
                text = "".join(self._text_parts).strip()
                if text:
                    self.records.append((self._message_id, text))
            self._message_id = None
            self._message_depth = None
            self._service = False
            self._text_depth = None
            self._text_parts = []
        self._div_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._text_depth is not None:
            self._text_parts.append(data)


def _parse_html(content: bytes) -> list[tuple[str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise AcquisitionProtocolError("Telegram export HTML must be UTF-8") from None
    parser = _TelegramHTMLParser()
    parser.feed(text)
    parser.close()
    return parser.records


def _load_zip(path: Path) -> tuple[list[tuple[str, str]], str]:
    if path.stat().st_size > _MAX_EXPORT_BYTES:
        raise AcquisitionLimitExceeded("Telegram export archive exceeds maximum size")
    records: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if _MESSAGE_FILE.search(name) and not name.endswith("/")
        ]
        if not names:
            raise AcquisitionProtocolError("Telegram archive contains no messages HTML")
        for name in sorted(names):
            info = archive.getinfo(name)
            if info.file_size > _MAX_EXPORT_BYTES:
                raise AcquisitionLimitExceeded("Telegram HTML file exceeds maximum size")
            records.extend(_parse_html(archive.read(name)))
    return records, path.name


def _load_directory(path: Path) -> tuple[list[tuple[str, str]], str]:
    files = sorted(
        candidate
        for candidate in path.rglob("messages*.html")
        if candidate.is_file() and _MESSAGE_FILE.search(candidate.as_posix())
    )
    if not files:
        raise AcquisitionProtocolError("Telegram export contains no messages HTML")
    records: list[tuple[str, str]] = []
    total = 0
    for candidate in files:
        total += candidate.stat().st_size
        if total > _MAX_EXPORT_BYTES:
            raise AcquisitionLimitExceeded("Telegram export exceeds maximum size")
        records.extend(_parse_html(candidate.read_bytes()))
    return records, path.name


def load_telegram_desktop_export(path: str | Path) -> AcquisitionBatch:
    """Load a Telegram Desktop HTML export ZIP/directory without sender identities."""

    source = Path(path)
    if source.is_dir():
        raw_records, source_ref = _load_directory(source)
    elif source.is_file() and source.suffix.lower() == ".zip":
        raw_records, source_ref = _load_zip(source)
    else:
        raise AcquisitionProtocolError(
            "Telegram export must be a ZIP file or export directory"
        )

    comments: dict[str, AcquiredComment] = {}
    for raw_id, raw_text in raw_records:
        if len(comments) >= _MAX_MESSAGES:
            raise AcquisitionLimitExceeded("Telegram export exceeds maximum message count")
        comment_id = raw_id.strip()
        if not comment_id or any(char.isspace() for char in comment_id):
            raise AcquisitionProtocolError("Telegram message id is invalid")
        text = bounded_text(raw_text)
        comments[comment_id] = AcquiredComment(
            platform=Platform.TELEGRAM,
            comment_id=comment_id,
            source_id="telegram-desktop-export",
            text=text,
        )

    if not comments:
        raise AcquisitionProtocolError("Telegram export contains no text messages")
    return AcquisitionBatch.build(
        platform=Platform.TELEGRAM,
        source_ref=source_ref,
        comments=tuple(comments.values()),
    )
