# sitemapr

Generate XML sitemaps from page definitions or URL streams, with automatic file splitting.

## Installation

```sh
pip install sitemapr
```

## Quick start

```python
from pathlib import Path
from sitemapr import Page, Param, SiteMapr

output = Path("sitemaps")
output.mkdir(exist_ok=True)

sitemapr = SiteMapr(
    "https://example.com",
    pages=[
        Page(path="/"),
        Page(
            path="/posts/{id}",
            path_params=[Param(name="id", values=["1", "2", "3"])],
        ),
    ],
)
sitemapr.save(str(output))
```

Find the generated sitemap at `sitemaps/sitemap.xml`.
Use `query_params` for query strings and `lastmod`, `changefreq`, or `priority` for URL metadata.

## Streaming URLs

Pass an iterable of `SiteMapUrl` objects to `save()`:

```python
from sitemapr import SiteMapr, SiteMapUrl

sitemapr = SiteMapr("https://example.com")
urls = (SiteMapUrl(loc=f"https://example.com/posts/{post_id}") for post_id in range(100000))
sitemapr.save("sitemaps", urls=urls)
```

For an async iterable of `SiteMapUrl` objects, use `asave()`:

```python
await sitemapr.asave("sitemaps", urls=async_urls)
```

## License

[MIT](LICENSE)
