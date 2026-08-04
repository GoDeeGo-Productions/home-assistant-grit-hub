#!/usr/bin/env python3
"""Create a bounded, best-effort redacted copy of a GRIT/Home Assistant log."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

MAX_INPUT_BYTES = 10 * 1024 * 1024
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[^\s,;]+"),
        "Authorization: Bearer [REDACTED]",
    ),
    (
        re.compile(r"(?i)\bBearer\s+[^\s,;]+"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(r"(?i)(\bauth_token=)[^&\s]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"\bgrit_[A-Za-z0-9._~+/=-]{8,}\b"),
        "[REDACTED-GRIT-TOKEN]",
    ),
    (
        re.compile(
            r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
        ),
        "[REDACTED-IPV4]",
    ),
    (
        re.compile(
            r"(?i)(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])"
            r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
            r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+"
        ),
        "[REDACTED-EMAIL]",
    ),
)


def redact_text(value: str) -> str:
    """Return a best-effort redacted copy without retaining input globally."""
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def redact_file(input_path: Path, output_path: Path) -> None:
    """Read and redact one bounded file into a distinct new output file."""
    source = input_path.resolve(strict=True)
    target = output_path.resolve(strict=False)
    if source == target:
        raise ValueError("input and output must be different files")
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input log exceeds the maximum supported size")
    if not target.parent.is_dir():
        raise FileNotFoundError("output directory does not exist")

    with source.open("rb") as input_file:
        raw_content = input_file.read(MAX_INPUT_BYTES + 1)
    if len(raw_content) > MAX_INPUT_BYTES:
        raise ValueError("input log exceeds the maximum supported size")
    content = raw_content.decode("utf-8", errors="replace")
    with target.open("x", encoding="utf-8", newline="\n") as output_file:
        output_file.write(redact_text(content))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write a bounded best-effort redacted log copy. Manual review is "
            "still required before sharing."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        redact_file(args.input, args.output)
    except (OSError, ValueError) as err:
        raise SystemExit(f"Redaction failed: {err}") from None
    print("Redacted log copy written; manual privacy review is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
