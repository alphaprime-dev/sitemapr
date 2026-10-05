# sitemapr

Generate XML sitemaps from pages, with automatic file splitting.

## Installation

```sh
pip install sitemapr
```

## Quick start

```python
from pathlib import Path
from sitemapr import Page, SiteMapr

output = Path("sitemaps")
output.mkdir(exist_ok=True)

sitemap = SiteMapr("https://example.com")
pages = [
    Page(path="/"),
    Page(path="/posts/{id}", path_params={"id": ["1", "2", "3"]}),
]
sitemap.save(output, pages=pages)
```

Find the generated sitemap at `sitemaps/sitemap.xml`.
Use `query_params` for query strings and `lastmod`, `changefreq`, or `priority` for URL metadata.

## Streaming pages

For large inputs, pass a generator of pages to `save()`:

```python
pages = (Page(path=f"/posts/{post_id}") for post_id in range(100000))
sitemap.save(output, pages=pages)
```

For an async iterable of pages, use `asave()`:

```python
await sitemap.asave(output, pages=async_pages)
```

## License

[MIT](LICENSE)
