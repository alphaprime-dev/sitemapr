from collections.abc import AsyncIterable, Iterable, Iterator
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from sitemapr.models import Page, Param, SiteMapUrl

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_XML_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


class SiteMapr:
    """Generate sitemaps from declarative pages and streams of additional URLs.

    Args:
        base_url: The base URL of the website.
        pages: Pages to expand lazily. A generator is consumed only once.
        sitemap_base_url: The base URL used in the sitemap index; defaults to base_url.
    """

    def __init__(
        self,
        base_url: str,
        pages: Iterable[Page] = (),
        *,
        sitemap_base_url: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._sitemap_base_url = sitemap_base_url or base_url
        self._pages = pages

    def save(
        self,
        dirname: str,
        *,
        urls: Iterable[SiteMapUrl] = (),
        chunk_size: int = 50000,
    ) -> None:
        """Write pages followed by additional URLs, without buffering either stream.

        ``chunk_size`` limits URLs per file, not the number held in memory.
        The caller owns supplied iterators and must close resource-backed sources
        when saving fails. Partial output files may remain after a failure.
        """
        with _SitemapWriter(dirname, self._sitemap_base_url, chunk_size) as writer:
            for url in self.iter_urls():
                writer.write(url)
            for url in urls:
                writer.write(url)

    async def asave(
        self,
        dirname: str,
        *,
        urls: AsyncIterable[SiteMapUrl],
        chunk_size: int = 50000,
    ) -> None:
        """Write pages followed by an async URL stream using the same file writer.

        URL retrieval is asynchronous; local file writes use buffered synchronous IO.
        The caller owns the async iterator; use ``contextlib.aclosing`` for async
        generators that hold resources. Partial files may remain after a failure
        or cancellation, but all output file handles are closed.
        """
        with _SitemapWriter(dirname, self._sitemap_base_url, chunk_size) as writer:
            for url in self.iter_urls():
                writer.write(url)
            async for url in urls:
                writer.write(url)

    def iter_urls(self) -> Iterator[SiteMapUrl]:
        """Yield unescaped URLs from pages, expanding parameter combinations lazily."""
        for page in self._pages:
            yield from self._iter_page(page)

    def _iter_page(self, page: Page) -> Iterator[SiteMapUrl]:
        if any(not param.values for param in page.path_params + page.query_params):
            return

        # Nested iteration avoids itertools.product caching the generated combinations.
        for query_params in self._get_param_combinations(page.query_params):
            for path_params in self._get_param_combinations(page.path_params):
                path = page.path.format(**path_params)
                query_string = urlencode(query_params)
                loc = (
                    f"{self._base_url}{path}?{query_string}"
                    if query_string
                    else f"{self._base_url}{path}"
                )
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
                yield SiteMapUrl(
                    loc=loc,
                    lastmod=lastmod,
                    changefreq=changefreq,
                    priority=priority,
                )

    def _get_param_combinations(
        self, params: list[Param], index: int = 0
    ) -> Iterator[dict[str, str]]:
        if index == len(params):
            yield {}
            return

        param = params[index]
        for value in param.values:
            for remaining in self._get_param_combinations(params, index + 1):
                yield {param.name: value, **remaining}


class _SitemapWriter:
    def __init__(self, dirname: str, base_url: str, chunk_size: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._directory = Path(dirname)
        self._base_url = base_url
        self._chunk_size = chunk_size
        self._file: TextIOWrapper | None = None
        self._file_count = 0
        self._url_count = 0

    def __enter__(self) -> "_SitemapWriter":
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

    def write(self, url: SiteMapUrl) -> None:
        if self._url_count == self._chunk_size:
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
