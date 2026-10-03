import asyncio
import tracemalloc
from collections.abc import AsyncIterator, Callable, Iterator
from io import TextIOWrapper
from pathlib import Path
from typing import Literal, TypeVar
from xml.etree import ElementTree as ET

import pytest

from sitemapr import Page, Param, SiteMapr, SiteMapUrl

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
def test_streamed_urls_follow_pages_across_files(
    tmp_path: Path,
    mode: Literal["sync", "async"],
    url_count: int,
    expected_sizes: list[int],
) -> None:
    """Page URLs and streamed URLs are saved in order with complete metadata and index links."""
    # Given
    sitemap = SiteMapr(
        "https://example.com",
        pages=(page for page in [Page(path="/home")]),
        sitemap_base_url="https://cdn.example.com/maps",
    )
    urls = (
        SiteMapUrl(
            loc=f"https://example.com/posts/{idx}?q=한글&literal=&amp;<tag>",
            lastmod="2026-01-02T03:04:00+00:00",
            changefreq="daily",
            priority="0.7",
        )
        for idx in range(url_count)
    )

    # When
    _save(mode, sitemap, tmp_path, urls, chunk_size=3)

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
    urls = (SiteMapUrl(loc=f"https://example.com/posts/{idx}") for idx in range(20000))

    # When
    # Trace only generation and saving; parse the completed output after measurement.
    _, peak = _measure_peak_bytes(lambda: _save(mode, sitemap, tmp_path, urls))

    # Then
    assert peak < 2 * 1024 * 1024
    assert len(ET.parse(tmp_path / "sitemap.xml").getroot()) == 20000


def test_large_parameter_product_yields_first_url_with_bounded_memory() -> None:
    """The first URL of a large query/path product is available within 1 MiB of traced memory."""
    # Given
    values = [str(idx) for idx in range(100)]
    sitemap = SiteMapr(
        "https://example.com",
        pages=[
            Page(
                path="/{category}/{id}",
                path_params=[
                    Param(name="category", values=values),
                    Param(name="id", values=values),
                ],
                query_params=[Param(name="a", values=values), Param(name="b", values=values)],
            )
        ],
    )

    # When
    first, peak = _measure_peak_bytes(lambda: next(sitemap.iter_urls()))

    # Then
    assert first.loc == "https://example.com/0/0?a=0&b=0"
    assert peak < 1024 * 1024


def test_page_generator_is_consumed_lazily_without_replay() -> None:
    """Page generators are consumed on demand and produce no URLs after being exhausted."""
    # Given
    consumed: list[str] = []

    def pages() -> Iterator[Page]:
        for name in ("first", "second"):
            consumed.append(name)
            yield Page(path=f"/{name}")

    # When
    sitemap = SiteMapr("https://example.com", pages=pages())
    consumed_after_construction = consumed.copy()
    urls = sitemap.iter_urls()
    first = next(urls).loc
    consumed_after_first_url = consumed.copy()
    remaining = [url.loc for url in urls]
    replayed = list(sitemap.iter_urls())

    # Then
    assert consumed_after_construction == []
    assert consumed_after_first_url == ["first"]
    assert consumed == ["first", "second"]
    assert first == "https://example.com/first"
    assert remaining == ["https://example.com/second"]
    assert replayed == []


def test_query_and_path_parameters_produce_all_urls_in_order() -> None:
    """Every query value is paired with every path value in declaration order."""
    # Given
    sitemap = SiteMapr(
        "https://example.com",
        pages=[
            Page(
                path="/posts/{id}",
                path_params=[Param(name="id", values=["1", "2"])],
                query_params=[Param(name="sort", values=["asc", "desc"])],
            )
        ],
    )

    # When
    urls = [url.loc for url in sitemap.iter_urls()]

    # Then
    assert urls == [
        "https://example.com/posts/1?sort=asc",
        "https://example.com/posts/2?sort=asc",
        "https://example.com/posts/1?sort=desc",
        "https://example.com/posts/2?sort=desc",
    ]


@pytest.mark.parametrize("empty_parameter", ["path", "query"])
def test_empty_parameter_values_produce_no_urls(empty_parameter: str, tmp_path: Path) -> None:
    """A page with an empty path or query parameter produces no URLs or sitemap files."""
    # Given
    sitemap = SiteMapr(
        "https://example.com",
        pages=[
            Page(
                path="/posts/{id}",
                path_params=[Param(name="id", values=[] if empty_parameter == "path" else ["1"])],
                query_params=[
                    Param(name="tag", values=[] if empty_parameter == "query" else ["news"]),
                    Param(name="sort", values=["asc"]),
                ],
            )
        ],
    )

    # When
    sitemap.save(str(tmp_path))

    # Then
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_source_failure_closes_output_without_publishing_index(
    tmp_path: Path, mode: Literal["sync", "async"], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source failure propagates, closes output handles, and leaves no completed sitemap index."""
    # Given
    files = _track_output_files(monkeypatch)

    def urls() -> Iterator[SiteMapUrl]:
        yield SiteMapUrl(loc="https://example.com/one")
        yield SiteMapUrl(loc="https://example.com/two")
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

        async def urls() -> AsyncIterator[SiteMapUrl]:
            yield SiteMapUrl(loc="https://example.com/one")
            waiting.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            SiteMapr("https://example.com").asave(str(tmp_path), urls=urls())
        )
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

    def urls() -> Iterator[SiteMapUrl]:
        nonlocal consumed
        consumed = True
        yield SiteMapUrl(loc="https://example.com/one")

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
    urls: Iterator[SiteMapUrl],
    *,
    chunk_size: int = 50000,
) -> None:
    if mode == "sync":
        sitemap.save(str(directory), urls=urls, chunk_size=chunk_size)
    else:
        asyncio.run(sitemap.asave(str(directory), urls=_as_async(urls), chunk_size=chunk_size))


async def _as_async(urls: Iterator[SiteMapUrl]) -> AsyncIterator[SiteMapUrl]:
    for url in urls:
        yield url


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
