# sitemapr

`sitemapr` is a Python library designed to generate and save sitemaps for websites. It allows for the creation of detailed sitemaps with customizable parameters, making it easier for search engines to crawl and index web pages efficiently.

## Features

- Generate sitemaps with dynamic URL parameters.
- Split large sitemaps into chunks to comply with sitemap index specifications.
- Customizable base URLs for sitemaps and websites.

## Installation

SiteMapr can be easily installed using pip. Ensure you have pip installed and run the following command:

```sh
pip install sitemapr
```

This command will download and install SiteMapr along with its dependencies.

## Quick Start

Here's how to quickly generate a sitemap for your website using SiteMapr:

1. **Define Your Pages**: First, define the pages you want to include in your sitemap, including any dynamic path or query parameters.

2. **Create a SiteMapr Instance**: Initialize SiteMapr with your website's base URL and the pages you've defined.

3. **Save Your Sitemap**: Choose a directory and save your sitemap, specifying chunk sizes if needed.

### Example

```python
from sitemapr import Page, Param, SiteMapr

# Define the pages of your site
pages = [
    Page(
        path="",
        query_params=[
            Param(name="page", values=["home", "about", "contact"]),
            Param(name="sort", values=["asc", "desc"]),
        ],
        priority="1.0",
    ),
    Page(
        path="/blog",
        query_params=[
            Param(name="page", values=["1", "2", "3"]),
            Param(name="sort", values=["asc", "desc"]),
        ],
        # For lastmod, priority, and changefreq field, you can use callback function for more precise control
        lastmod=lambda loc, path_params, query_params: "2024-05-07T00:00:00+00"
    ),
    Page(
        path="/blog/{id}",
        path_params=[Param(name="id", values=["1", "2", "3"])],
    ),
]

# Initialize SiteMapr with your website's base URL and the defined pages
sitemapr = SiteMapr(base_url="https://example.com", pages=pages)

# Save the sitemap to the specified directory
sitemapr.save("/path/to/your/sitemap/directory")
```

## Streaming URLs

Pass an iterable of `SiteMapUrl` objects to `save()`. URLs from `pages` are written
first, followed by `urls`. Both inputs are consumed once in order, without loading
all URLs or parameter combinations into memory. `pages` may also be a generator.

```python
from sitemapr import Page, SiteMapr, SiteMapUrl

sitemapr = SiteMapr("https://example.com", pages=[Page(path="/about")])
urls = (SiteMapUrl(loc=f"https://example.com/posts/{post_id}") for post_id in range(100000))
sitemapr.save("/path/to/output", urls=urls, chunk_size=50000)
```

`chunk_size` is the maximum number of URLs per file, not an in-memory batch size.
Each URL is written immediately through a buffered UTF-8 file handle. A single
output file is named `sitemap.xml`; multiple files are named `sitemap-0.xml`,
`sitemap-1.xml`, and so on, with `sitemap.xml` as their index. Empty inputs create
no files. Create the output directory before saving.

### Async sources

Use `asave()` for async generators, such as a streamed database query. It uses the
same writer and file splitting rules as `save()`.

```python
from collections.abc import AsyncIterator
from contextlib import aclosing
from tempfile import TemporaryDirectory

from sitemapr import SiteMapr, SiteMapUrl

async def post_urls() -> AsyncIterator[SiteMapUrl]:
    async with db.session() as session:
        result = await session.stream(query, execution_options={"yield_per": 1000})
        try:
            async for row in result:
                yield SiteMapUrl(
                    loc=f"https://example.com/posts/{row.id}",
                    lastmod=row.updated_at.isoformat(),
                )
        finally:
            await result.close()

async def generate_sitemap() -> None:
    sitemapr = SiteMapr("https://example.com")
    with TemporaryDirectory() as directory:
        async with aclosing(post_urls()) as urls:
            await sitemapr.asave(directory, urls=urls)
        # Upload or copy the completed files here, before the directory is removed.
```

This example assumes application-provided `db` and `query` objects. The library
has no database dependency. URL retrieval is asynchronous; local file writes use
buffered synchronous IO on the calling thread.

Callers own their input iterators. Use `closing()` or `aclosing()` around sources
that hold a database cursor or another resource, so failures while writing also
close those sources. Output handles are always closed on errors or cancellation.
Partial files may remain after an error; generate into a temporary directory and
publish only after saving succeeds.

### Changes in 0.4

- `SiteMapUrl.loc`, URLs returned by `iter_urls()`, and the `loc` passed to page
  callbacks use raw URL text. Pass `&`, not `&amp;`; the writer performs XML
  escaping once when saving.
- A `Param` with `values=[]` produces no URLs for that page. A page with no
  parameters still produces one URL.
- A nonpositive `chunk_size` raises `ValueError` before consuming inputs.
- Iterables are not cached. Supply fresh generators when saving again.

## License

`sitemapr` is released under the MIT License. See the LICENSE file for more details.
