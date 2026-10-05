from collections.abc import Callable
from typing import Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

ChangeFreq = Literal["always", "hourly", "daily", "weekly", "monthly", "yearly", "never"]

CallbackFn = Callable[[str, dict[str, str], dict[str, str]], T | None]


class Page(BaseModel):
    """A site-relative path or absolute URL, optionally expanded from parameter values.

    Metadata can be constant or a callback receiving the raw resolved URL and
    its path/query parameter dictionaries. Empty value lists produce no URLs.
    """

    path: str
    query_params: dict[str, list[str]] = {}
    path_params: dict[str, list[str]] = {}
    lastmod: str | None | CallbackFn[str] = None
    changefreq: ChangeFreq | None | CallbackFn[ChangeFreq] = None
    priority: str | None | CallbackFn[str] = None
