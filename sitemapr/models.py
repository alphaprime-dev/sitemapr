from collections.abc import Callable
from decimal import Decimal
from typing import Literal, TypeVar

from pydantic import BaseModel, field_validator

T = TypeVar("T")

ChangeFreq = Literal["always", "hourly", "daily", "weekly", "monthly", "yearly", "never"]

CallbackFn = Callable[[str, dict[str, str], dict[str, str]], T | None]


class Param(BaseModel):
    name: str
    values: list[str] = []


class Page(BaseModel):
    path: str
    query_params: list[Param] = []
    path_params: list[Param] = []
    lastmod: str | None | CallbackFn[str] = None
    changefreq: ChangeFreq | None | CallbackFn[ChangeFreq] = None
    priority: str | None | CallbackFn[str] = None


class SiteMapUrl(BaseModel):
    """A URL and its metadata; pass loc without XML escaping."""

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
