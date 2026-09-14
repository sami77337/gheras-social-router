"""Retired legacy entry point.

The historical Facebook auto-reply implementation has been superseded by the
Gheras Social Router V1 architecture. This module is intentionally fail-closed
so the legacy bot cannot be restarted accidentally from the active code line.

Historical implementation remains recoverable from Git history.
"""

from __future__ import annotations


def main() -> None:
    raise RuntimeError(
        "Legacy Facebook auto-reply runtime is retired. "
        "Use the governed Gheras Social Router deployment path instead."
    )


if __name__ == "__main__":
    main()
