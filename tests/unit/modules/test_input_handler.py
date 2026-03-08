"""Unit tests for modules.input_handler."""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.input_handler import process_sources


@pytest.mark.unit
def test_process_sources_merges_file_and_args_and_deduplicates(tmp_path: Path) -> None:
    src_file = tmp_path / "sources.txt"
    src_file.write_text(
        "\n".join(
            [
                "# comment",
                "@validchat",
                "t.me/validchan",
                "t.me/+Invite_HASH",
                "@validchat",
                "invalid source",
            ]
        ),
        encoding="utf-8",
    )

    out = process_sources(
        source_args=["@validchat", "t.me/othergood", "bad@@@"],
        file_path=str(src_file),
    )

    assert set(out) == {
        "@validchat",
        "t.me/validchan",
        "t.me/+Invite_HASH",
        "t.me/othergood",
    }


@pytest.mark.unit
def test_process_sources_missing_file_only_args() -> None:
    out = process_sources(
        source_args=["@chatone", "t.me/chattwo"],
        file_path="this_file_does_not_exist.txt",
    )

    assert set(out) == {"@chatone", "t.me/chattwo"}


@pytest.mark.unit
def test_process_sources_filters_short_usernames() -> None:
    out = process_sources(
        source_args=["@abcd", "@abcde", "t.me/abcd", "t.me/abcde"],
        file_path=None,
    )

    assert set(out) == {"@abcde", "t.me/abcde"}
