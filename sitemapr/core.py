from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Iterator
from decimal import Decimal
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType
from urllib.parse import urlencode, urlsplit, urlunsplit
from xml.sax.saxutils import escape

from pydantic import BaseModel, field_validator

from sitemapr.models import ChangeFreq, Page

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_XML_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


class SiteMapr:
    """Save page streams as sitemaps using a website URL and optional index URL."""

    def __init__(self, base_url: str, *, sitemap_base_url: str | None = None) -> None:
        self._base_url = base_url
        self._sitemap_base_url = sitemap_base_url or base_url

    def save(
        self,
        dirname: str | Path,
        *,
        pages: Iterable[Page],
        max_urls_per_file: int = 50000,
    ) -> None:
        """Expand and save a page stream in order without retaining a URL batch.

        Each call consumes only its supplied pages. ``max_urls_per_file`` limits URLs
        per file. The caller owns input iterators and must close resource-backed
        sources on failure. Partial output files may remain after a failure.
        """
        with _SitemapWriter(dirname, self._sitemap_base_url, max_urls_per_file) as writer:
            for page in pages:
                for url in self._iter_page(page):
                    writer.write(url)

    async def asave(
        self,
        dirname: str | Path,
        *,
        pages: AsyncIterable[Page],
        max_urls_per_file: int = 50000,
    ) -> None:
        """Expand and save an async page stream using the same file writer.

        Retrieval is asynchronous; local file writes use buffered synchronous IO.
        The caller owns the iterator; use ``contextlib.aclosing`` for async
        generators that hold resources. Output handles are closed on failure or
        cancellation, but partial files may remain.
        """
        with _SitemapWriter(dirname, self._sitemap_base_url, max_urls_per_file) as writer:
            async for page in pages:
                for url in self._iter_page(page):
                    writer.write(url)

    def _iter_page(self, page: Page) -> Iterator[_SitemapUrl]:
        path_options = list(page.path_params.items())
        query_options = list(page.query_params.items())
        if any(not values for _, values in path_options + query_options):
            return

        # Nested iteration avoids itertools.product caching the generated combinations.
        for query_params in self._iter_param_combinations(query_options):
            for path_params in self._iter_param_combinations(path_options):
                path = page.path.format(**path_params)
                loc = (
                    path if path.startswith(("http://", "https://")) else f"{self._base_url}{path}"
                )
                if query_params:
                    parts = urlsplit(loc)
                    query = "&".join(filter(None, (parts.query, urlencode(query_params))))
                    loc = urlunsplit(parts._replace(query=query))
                lastmod = (
                    page.lastmod(loc, path_params, query_params)
                    if callable(page.lastmod)
                    else page.lastmod
                )
                changefreq = (
                    page.changefreq(loc, path_params, query_params)
                    if callable(page.changefreq)
                    else page.changefreq
                )
                priority = (
                    page.priority(loc, path_params, query_params)
                    if callable(page.priority)
                    else page.priority
                )
                yield _SitemapUrl(
                    loc=loc,
                    lastmod=lastmod,
                    changefreq=changefreq,
                    priority=priority,
                )

    def _iter_param_combinations(
        self, params: list[tuple[str, list[str]]], index: int = 0
    ) -> Iterator[dict[str, str]]:
        if index == len(params):
            yield {}
            return

        name, values = params[index]
        for value in values:
            for remaining in self._iter_param_combinations(params, index + 1):
                yield {name: value, **remaining}


class _SitemapWriter:
    def __init__(self, dirname: str | Path, base_url: str, max_urls_per_file: int) -> None:
        if max_urls_per_file <= 0:
            raise ValueError("max_urls_per_file must be positive")
        self._directory = Path(dirname)
        self._base_url = base_url
        self._max_urls_per_file = max_urls_per_file
        self._file: TextIOWrapper | None = None
        self._file_count = 0
        self._url_count = 0

    def __enter__(self) -> _SitemapWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            if self._file is not None:
                self._file.close()
                self._file = None
            return

        self._close_file()
        if self._file_count == 1:
            (self._directory / "sitemap-0.xml").replace(self._directory / "sitemap.xml")
        elif self._file_count > 1:
            self._write_index()

    def write(self, url: _SitemapUrl) -> None:
        if self._url_count == self._max_urls_per_file:
            self._close_file()
        if self._file is None:
            self._file = (self._directory / f"sitemap-{self._file_count}.xml").open(
                "w", encoding="utf-8"
            )
            self._file_count += 1
            self._url_count = 0
            self._file.write(f'{_XML_HEADER}<urlset xmlns="{_XML_NAMESPACE}">')

        self._file.write(f"<url><loc>{escape(url.loc)}</loc>")
        for name, value in (
            ("lastmod", url.lastmod),
            ("changefreq", url.changefreq),
            ("priority", url.priority),
        ):
            if value:
                self._file.write(f"<{name}>{escape(value)}</{name}>")
        self._file.write("</url>")
        self._url_count += 1

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.write("</urlset>")
            finally:
                self._file.close()
                self._file = None

    def _write_index(self) -> None:
        with (self._directory / "sitemap.xml").open("w", encoding="utf-8") as f:
            f.write(f'{_XML_HEADER}<sitemapindex xmlns="{_XML_NAMESPACE}">')
            for idx in range(self._file_count):
                loc = escape(f"{self._base_url}/sitemap-{idx}.xml")
                f.write(f"<sitemap><loc>{loc}</loc></sitemap>")
            f.write("</sitemapindex>")


class _SitemapUrl(BaseModel):
    """Resolved URL metadata, validated before serialization."""

    # Refer to https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap?hl=ko#xml
    loc: str
    lastmod: str | None = None
    changefreq: ChangeFreq | None = None  # Google ignores this
    priority: str | None = None  # Google ignores this

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            priority = Decimal(v)
        except Exception as e:
            raise ValueError("Priority must be a valid decimal string between 0.0 and 1.0") from e

        if 0 <= priority <= 1:
            return f"{priority:.1f}"

        raise ValueError("Priority must be between 0.0 and 1.0")
