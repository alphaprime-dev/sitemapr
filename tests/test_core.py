import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from sitemapr import Page, SiteMapr


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_save_expands_all_parameter_combinations_with_metadata(
    tmp_path: Path, asynchronous: bool
) -> None:
    """Saving pairs every query/path value in order and evaluates metadata for each raw URL."""
    # Given
    callback_inputs: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def lastmod(loc: str, path: dict[str, str], query: dict[str, str]) -> str | None:
        callback_inputs.append((loc, path.copy(), query.copy()))
        return "2026-01-02T03:04:00+00:00" if path["id"] == "1" else None

    pages = [
        Page(
            path="/posts/{id}",
            path_params={"id": ["1", "2"]},
            query_params={"lang": ["ko", "en"], "sort": ["asc"]},
            lastmod=lastmod,
            changefreq=lambda _loc, _path, query: "daily" if query["lang"] == "ko" else None,
            priority=lambda _loc, path, _query: "1" if path["id"] == "1" else "0.7",
        )
    ]
    sitemap = SiteMapr("https://example.com")

    # When
    if asynchronous:
        asyncio.run(sitemap.asave(tmp_path, pages=_as_async(pages)))
    else:
        sitemap.save(tmp_path, pages=pages)

    # Then
    root = ET.parse(tmp_path / "sitemap.xml").getroot()
    entries = [{child.tag.rsplit("}", 1)[-1]: child.text for child in entry} for entry in root]
    assert entries == [
        {
            "loc": "https://example.com/posts/1?lang=ko&sort=asc",
            "lastmod": "2026-01-02T03:04:00+00:00",
            "changefreq": "daily",
            "priority": "1.0",
        },
        {
            "loc": "https://example.com/posts/2?lang=ko&sort=asc",
            "changefreq": "daily",
            "priority": "0.7",
        },
        {
            "loc": "https://example.com/posts/1?lang=en&sort=asc",
            "lastmod": "2026-01-02T03:04:00+00:00",
            "priority": "1.0",
        },
        {"loc": "https://example.com/posts/2?lang=en&sort=asc", "priority": "0.7"},
    ]
    assert callback_inputs == [
        (
            "https://example.com/posts/1?lang=ko&sort=asc",
            {"id": "1"},
            {"lang": "ko", "sort": "asc"},
        ),
        (
            "https://example.com/posts/2?lang=ko&sort=asc",
            {"id": "2"},
            {"lang": "ko", "sort": "asc"},
        ),
        (
            "https://example.com/posts/1?lang=en&sort=asc",
            {"id": "1"},
            {"lang": "en", "sort": "asc"},
        ),
        (
            "https://example.com/posts/2?lang=en&sort=asc",
            {"id": "2"},
            {"lang": "en", "sort": "asc"},
        ),
    ]


@pytest.mark.parametrize("callback", [False, True], ids=["constant", "callback"])
def test_invalid_priority_is_rejected_before_writing(tmp_path: Path, callback: bool) -> None:
    """An out-of-range constant or callback priority is rejected before creating output files."""
    # Given
    page = Page(
        path="/posts/1",
        priority=(lambda _loc, _path, _query: "1.1") if callback else "1.1",
    )

    # When
    with pytest.raises(ValidationError, match="Priority must be between 0.0 and 1.0"):
        SiteMapr("https://example.com").save(tmp_path, pages=[page])

    # Then
    assert list(tmp_path.iterdir()) == []


def test_relative_paths_and_absolute_urls_share_one_input(tmp_path: Path) -> None:
    """Relative paths and absolute URLs retain their existing query and fragment when saved."""
    # Given
    pages = [
        Page(path="/posts/1"),
        Page(path="https://other.example.com/posts?feed=1#section", query_params={"lang": ["ko"]}),
    ]

    # When
    SiteMapr("https://example.com/app").save(tmp_path, pages=pages)

    # Then
    root = ET.parse(tmp_path / "sitemap.xml").getroot()
    assert [entry.findtext("{*}loc") for entry in root] == [
        "https://example.com/app/posts/1",
        "https://other.example.com/posts?feed=1&lang=ko#section",
    ]


def test_empty_page_stream_creates_no_files(tmp_path: Path) -> None:
    """Saving an empty page stream creates no sitemap or index files."""
    # Given
    sitemap = SiteMapr("https://example.com")

    # When
    sitemap.save(tmp_path, pages=[])

    # Then
    assert list(tmp_path.iterdir()) == []


async def _as_async(pages: list[Page]) -> AsyncIterator[Page]:
    for page in pages:
        yield page
