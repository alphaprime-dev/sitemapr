import asyncio
from collections.abc import AsyncIterator, Iterable, Iterator
from io import TextIOWrapper
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from sitemapr import Page, SiteMapr


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_save_expands_all_parameter_combinations_with_metadata(
    tmp_path: Path, mode: Literal["sync", "async"]
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
    _save(mode, sitemap, tmp_path, pages)

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


@pytest.mark.parametrize(
    ("mode", "url_count", "expected_sizes"),
    [
        ("sync", 2, [3]),
        ("sync", 5, [3, 3]),
        ("async", 6, [3, 3, 1]),
    ],
    ids=["single-file", "exact-chunks", "async-partial-chunk"],
)
def test_page_stream_preserves_order_across_files(
    tmp_path: Path,
    mode: Literal["sync", "async"],
    url_count: int,
    expected_sizes: list[int],
) -> None:
    """Page streams are saved in order with complete metadata and sitemap index links."""
    # Given
    sitemap = SiteMapr(
        "https://example.com",
        sitemap_base_url="https://cdn.example.com/maps",
    )

    def pages() -> Iterator[Page]:
        yield Page(path="/home")
        for idx in range(url_count):
            yield Page(
                path=f"https://example.com/posts/{idx}?q=한글&literal=&amp;<tag>",
                lastmod="2026-01-02T03:04:00+00:00",
                changefreq="daily",
                priority="0.7",
            )

    # When
    _save(mode, sitemap, tmp_path, pages(), max_urls_per_file=3)

    # Then
    root = ET.parse(tmp_path / "sitemap.xml").getroot()
    if len(expected_sizes) == 1:
        assert [path.name for path in tmp_path.iterdir()] == ["sitemap.xml"]
        chunks = [root]
    else:
        assert [entry.findtext("{*}loc") for entry in root] == [
            f"https://cdn.example.com/maps/sitemap-{idx}.xml" for idx in range(len(expected_sizes))
        ]
        assert len(list(tmp_path.iterdir())) == len(expected_sizes) + 1
        chunks = [
            ET.parse(tmp_path / f"sitemap-{idx}.xml").getroot()
            for idx in range(len(expected_sizes))
        ]
    assert [len(chunk) for chunk in chunks] == expected_sizes
    entries = [entry for chunk in chunks for entry in chunk]
    assert [entry.findtext("{*}loc") for entry in entries] == [
        "https://example.com/home",
        *(f"https://example.com/posts/{idx}?q=한글&literal=&amp;<tag>" for idx in range(url_count)),
    ]
    for entry in entries[1:]:
        assert entry.findtext("{*}lastmod") == "2026-01-02T03:04:00+00:00"
        assert entry.findtext("{*}changefreq") == "daily"
        assert entry.findtext("{*}priority") == "0.7"


@pytest.mark.parametrize("empty_parameter", ["path", "query"])
def test_empty_parameter_values_produce_no_urls(empty_parameter: str, tmp_path: Path) -> None:
    """A page with an empty path or query parameter produces no URLs or sitemap files."""
    # Given
    pages = [
        Page(
            path="/posts/{id}",
            path_params={"id": [] if empty_parameter == "path" else ["1"]},
            query_params={
                "tag": [] if empty_parameter == "query" else ["news"],
                "sort": ["asc"],
            },
        )
    ]

    # When
    SiteMapr("https://example.com").save(tmp_path, pages=pages)

    # Then
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_source_failure_closes_output_without_publishing_index(
    tmp_path: Path, mode: Literal["sync", "async"], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source failure propagates, closes output handles, and leaves no completed sitemap index."""
    # Given
    files = _track_output_files(monkeypatch)

    def urls() -> Iterator[Page]:
        yield Page(path="https://example.com/one")
        yield Page(path="https://example.com/two")
        raise RuntimeError("source unavailable")

    # When
    with pytest.raises(RuntimeError, match="source unavailable"):
        _save(mode, SiteMapr("https://example.com"), tmp_path, urls(), max_urls_per_file=1)

    # Then
    assert len(files) == 2
    assert all(file.closed for file in files)
    assert not (tmp_path / "sitemap.xml").exists()


def test_cancelled_async_save_closes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling an async save closes output and propagates cancellation."""
    # Given
    files = _track_output_files(monkeypatch)

    async def cancel_save() -> None:
        waiting = asyncio.Event()

        async def urls() -> AsyncIterator[Page]:
            yield Page(path="https://example.com/one")
            waiting.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(SiteMapr("https://example.com").asave(tmp_path, pages=urls()))
        # Cancel only after the first URL was written and retrieval has suspended.
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # When
    asyncio.run(cancel_save())

    # Then
    assert len(files) == 1
    assert files[0].closed
    assert not (tmp_path / "sitemap.xml").exists()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("max_urls_per_file", [0, -1], ids=["zero", "negative"])
def test_invalid_url_limit_does_not_consume_source(
    tmp_path: Path, mode: Literal["sync", "async"], max_urls_per_file: int
) -> None:
    """A nonpositive URL limit is rejected before consuming pages or creating files."""
    # Given
    consumed = False

    def urls() -> Iterator[Page]:
        nonlocal consumed
        consumed = True
        yield Page(path="https://example.com/one")

    # When
    with pytest.raises(ValueError, match="max_urls_per_file must be positive"):
        _save(
            mode,
            SiteMapr("https://example.com"),
            tmp_path,
            urls(),
            max_urls_per_file=max_urls_per_file,
        )

    # Then
    assert not consumed
    assert list(tmp_path.iterdir()) == []


def _save(
    mode: Literal["sync", "async"],
    sitemap: SiteMapr,
    directory: Path,
    pages: Iterable[Page],
    *,
    max_urls_per_file: int = 50000,
) -> None:
    if mode == "sync":
        sitemap.save(directory, pages=pages, max_urls_per_file=max_urls_per_file)
    else:
        asyncio.run(
            sitemap.asave(directory, pages=_as_async(pages), max_urls_per_file=max_urls_per_file)
        )


async def _as_async(pages: Iterable[Page]) -> AsyncIterator[Page]:
    for page in pages:
        yield page


def _track_output_files(monkeypatch: pytest.MonkeyPatch) -> list[TextIOWrapper]:
    files: list[TextIOWrapper] = []
    original_open = Path.open

    def tracked_open(
        path: Path, mode: Literal["w"] = "w", *, encoding: str | None = None
    ) -> TextIOWrapper:
        file = original_open(path, mode, encoding=encoding)
        files.append(file)
        return file

    monkeypatch.setattr(Path, "open", tracked_open)
    return files
