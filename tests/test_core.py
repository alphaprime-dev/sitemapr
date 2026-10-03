import pathlib

import pytest
from pydantic import ValidationError

from sitemapr import Page, Param, SiteMapr, SiteMapUrl


def test_iter_url_works():
    """iter_url should return all possible urls."""
    # given
    base_url = "https://example.com"
    pages = [
        Page(
            path="",
            query_params=[
                Param(name="page", values=["home", "about", "contact"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
            lastmod="2021-01-01T00:00:00+00:00",
        ),
        Page(
            path="/blog",
            query_params=[
                Param(name="page", values=["1", "2", "3"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
            lastmod=lambda _loc, _page_params, query_params: (
                "2021-01-02T00:00:00+00:00" if query_params["page"] == "1" else None
            ),
        ),
        Page(
            path="/blog/{id}",
            path_params=[Param(name="id", values=["1", "2", "3"])],
            changefreq="daily",
            priority=lambda _loc, path_params, _query_params: (
                "1.0" if path_params["id"] == "1" else "0.7"
            ),
        ),
    ]
    sitemapr = SiteMapr(base_url=base_url, pages=pages)

    # when
    actuals = list(sitemapr.iter_urls())

    # then
    expected = [
        SiteMapUrl(
            loc="https://example.com?page=home&sort=asc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com?page=home&sort=desc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com?page=about&sort=asc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com?page=about&sort=desc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com?page=contact&sort=asc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com?page=contact&sort=desc",
            lastmod="2021-01-01T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=1&sort=asc",
            lastmod="2021-01-02T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=1&sort=desc",
            lastmod="2021-01-02T00:00:00+00:00",
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=2&sort=asc",
            lastmod=None,
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=2&sort=desc",
            lastmod=None,
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=3&sort=asc",
            lastmod=None,
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog?page=3&sort=desc",
            lastmod=None,
            changefreq=None,
            priority=None,
        ),
        SiteMapUrl(
            loc="https://example.com/blog/1",
            lastmod=None,
            changefreq="daily",
            priority="1.0",
        ),
        SiteMapUrl(
            loc="https://example.com/blog/2",
            lastmod=None,
            changefreq="daily",
            priority="0.7",
        ),
        SiteMapUrl(
            loc="https://example.com/blog/3",
            lastmod=None,
            changefreq="daily",
            priority="0.7",
        ),
    ]
    assert actuals == expected


def test_iter_url_raises_error_when_priority_is_invalid():
    """iter_url should raise an error when priority is invalid."""
    # given
    invalid_priority = "1.1"

    base_url = "https://example.com"
    pages = [
        Page(
            path="",
            query_params=[
                Param(name="page", values=["home", "about", "contact"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
            priority=invalid_priority,
        ),
    ]
    sitemapr = SiteMapr(base_url=base_url, pages=pages)

    # when, then
    with pytest.raises(ValidationError):
        list(sitemapr.iter_urls())


def test_save_works(tmp_path: pathlib.Path):
    """save should save sitemap.xml when there is only one page."""
    # given
    base_url = "https://example.com"
    pages = [
        Page(
            path="",
            query_params=[
                Param(name="page", values=["home", "about", "contact"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
        ),
        Page(
            path="/blog",
            query_params=[
                Param(name="page", values=["1", "2", "3"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
        ),
        Page(
            path="/blog/{id}",
            path_params=[Param(name="id", values=["1", "2", "3"])],
        ),
    ]
    sitemapr = SiteMapr(base_url=base_url, pages=pages)

    # when
    dirname = str(tmp_path)
    sitemapr.save(dirname, chunk_size=50000)

    # then
    with open(f"{dirname}/sitemap.xml") as f:
        content = f.read()
        assert (
            content
            == '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com?page=home&amp;sort=asc</loc></url><url><loc>https://example.com?page=home&amp;sort=desc</loc></url><url><loc>https://example.com?page=about&amp;sort=asc</loc></url><url><loc>https://example.com?page=about&amp;sort=desc</loc></url><url><loc>https://example.com?page=contact&amp;sort=asc</loc></url><url><loc>https://example.com?page=contact&amp;sort=desc</loc></url><url><loc>https://example.com/blog?page=1&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=1&amp;sort=desc</loc></url><url><loc>https://example.com/blog?page=2&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=2&amp;sort=desc</loc></url><url><loc>https://example.com/blog?page=3&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=3&amp;sort=desc</loc></url><url><loc>https://example.com/blog/1</loc></url><url><loc>https://example.com/blog/2</loc></url><url><loc>https://example.com/blog/3</loc></url></urlset>'
        )


def test_save_works_with_multiple_chunks(tmp_path: pathlib.Path):
    """save should save sitemap.xml and sitemap-index.xml when there are multiple chunks."""

    # given
    base_url = "https://example.com"
    pages = [
        Page(
            path="",
            query_params=[
                Param(name="page", values=["home", "about", "contact"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
        ),
        Page(
            path="/blog",
            query_params=[
                Param(name="page", values=["1", "2", "3"]),
                Param(name="sort", values=["asc", "desc"]),
            ],
        ),
        Page(
            path="/blog/{id}",
            path_params=[Param(name="id", values=["1", "2", "3"])],
        ),
    ]
    sitemapr = SiteMapr(base_url=base_url, pages=pages)

    # when
    dirname = str(tmp_path)
    sitemapr.save(dirname, chunk_size=10)

    # then
    with open(f"{dirname}/sitemap.xml") as f:
        content = f.read()
        assert (
            content
            == '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/sitemap-0.xml</loc></sitemap><sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap></sitemapindex>'
        )

    with open(f"{dirname}/sitemap-0.xml") as f:
        content = f.read()
        assert (
            content
            == '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com?page=home&amp;sort=asc</loc></url><url><loc>https://example.com?page=home&amp;sort=desc</loc></url><url><loc>https://example.com?page=about&amp;sort=asc</loc></url><url><loc>https://example.com?page=about&amp;sort=desc</loc></url><url><loc>https://example.com?page=contact&amp;sort=asc</loc></url><url><loc>https://example.com?page=contact&amp;sort=desc</loc></url><url><loc>https://example.com/blog?page=1&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=1&amp;sort=desc</loc></url><url><loc>https://example.com/blog?page=2&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=2&amp;sort=desc</loc></url></urlset>'
        )

    with open(f"{dirname}/sitemap-1.xml") as f:
        content = f.read()
        assert (
            content
            == '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/blog?page=3&amp;sort=asc</loc></url><url><loc>https://example.com/blog?page=3&amp;sort=desc</loc></url><url><loc>https://example.com/blog/1</loc></url><url><loc>https://example.com/blog/2</loc></url><url><loc>https://example.com/blog/3</loc></url></urlset>'
        )


def test_save_works_without_pages(tmp_path: pathlib.Path):
    """save should not save anything when there are no pages."""
    # given
    base_url = "https://example.com"
    pages: list[Page] = []
    sitemapr = SiteMapr(base_url=base_url, pages=pages)

    # when
    dirname = str(tmp_path)
    sitemapr.save(dirname, chunk_size=10)

    # then
    assert not list(tmp_path.iterdir())
