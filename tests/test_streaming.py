import asyncio
import tracemalloc
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from io import TextIOWrapper
from pathlib import Path
from typing import Literal, TypeVar
from xml.etree import ElementTree as ET

import pytest

from sitemapr import Page, SiteMapr

T = TypeVar("T")


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
    _save(mode, sitemap, tmp_path, pages(), chunk_size=3)

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


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_generated_urls_use_bounded_memory(tmp_path: Path, mode: Literal["sync", "async"]) -> None:
    """Saving 20,000 generated URLs uses less than 2 MiB of traced working memory."""
    # Given
    sitemap = SiteMapr("https://example.com")
    urls = (Page(path=f"https://example.com/posts/{idx}") for idx in range(20000))

    # When
    # Trace only generation and saving; parse the completed output after measurement.
    _, peak = _measure_peak_bytes(lambda: _save(mode, sitemap, tmp_path, urls))

    # Then
    assert peak < 2 * 1024 * 1024
    assert len(ET.parse(tmp_path / "sitemap.xml").getroot()) == 20000


def test_parameter_combinations_are_saved_with_bounded_memory(tmp_path: Path) -> None:
    """Saving 10,000 query combinations uses less than 1 MiB of traced working memory."""
    # Given
    values = [str(idx) for idx in range(100)]
    pages = [Page(path="/posts", query_params={"a": values, "b": values})]
    sitemap = SiteMapr("https://example.com")

    # When
    _, peak = _measure_peak_bytes(lambda: sitemap.save(tmp_path, pages=pages))

    # Then
    assert peak < 1024 * 1024
    root = ET.parse(tmp_path / "sitemap.xml").getroot()
    assert len(root) == 10000
    assert root[0].findtext("{*}loc") == "https://example.com/posts?a=0&b=0"
    assert root[-1].findtext("{*}loc") == "https://example.com/posts?a=99&b=99"


def test_page_stream_is_consumed_lazily_without_replay(tmp_path: Path) -> None:
    """Saving consumes pages on demand and does not replay an exhausted input on a later save."""
    # Given
    consumed: list[str] = []
    consumed_at_metadata: list[list[str]] = []

    def lastmod(_loc: str, _path: dict[str, str], _query: dict[str, str]) -> None:
        consumed_at_metadata.append(consumed.copy())

    def pages() -> Iterator[Page]:
        for name in ("first", "second"):
            consumed.append(name)
            yield Page(path=f"/{name}", lastmod=lastmod)

    sitemap = SiteMapr("https://example.com")
    source = pages()
    second_output = tmp_path / "second"
    second_output.mkdir()

    # When
    sitemap.save(tmp_path, pages=source)
    sitemap.save(second_output, pages=source)

    # Then
    assert consumed_at_metadata == [["first"], ["first", "second"]]
    assert consumed == ["first", "second"]
    root = ET.parse(tmp_path / "sitemap.xml").getroot()
    assert [entry.findtext("{*}loc") for entry in root] == [
        "https://example.com/first",
        "https://example.com/second",
    ]
    assert list(second_output.iterdir()) == []


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
        _save(mode, SiteMapr("https://example.com"), tmp_path, urls(), chunk_size=1)

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
@pytest.mark.parametrize("chunk_size", [0, -1], ids=["zero", "negative"])
def test_invalid_chunk_size_does_not_consume_source(
    tmp_path: Path, mode: Literal["sync", "async"], chunk_size: int
) -> None:
    """A nonpositive chunk size is rejected before consuming URLs or creating files."""
    # Given
    consumed = False

    def urls() -> Iterator[Page]:
        nonlocal consumed
        consumed = True
        yield Page(path="https://example.com/one")

    # When
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        _save(mode, SiteMapr("https://example.com"), tmp_path, urls(), chunk_size=chunk_size)

    # Then
    assert not consumed
    assert list(tmp_path.iterdir()) == []


def _measure_peak_bytes(operation: Callable[[], T]) -> tuple[T, int]:
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    # Exclude earlier allocations and historical peaks from this measurement.
    tracemalloc.reset_peak()
    baseline = tracemalloc.get_traced_memory()[0]
    try:
        result = operation()
        peak = tracemalloc.get_traced_memory()[1] - baseline
    finally:
        if not was_tracing:
            tracemalloc.stop()
    return result, peak


def _save(
    mode: Literal["sync", "async"],
    sitemap: SiteMapr,
    directory: Path,
    pages: Iterable[Page],
    *,
    chunk_size: int = 50000,
) -> None:
    if mode == "sync":
        sitemap.save(directory, pages=pages, chunk_size=chunk_size)
    else:
        asyncio.run(sitemap.asave(directory, pages=_as_async(pages), chunk_size=chunk_size))


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
