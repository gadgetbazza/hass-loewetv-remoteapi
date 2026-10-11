"""Programme artwork from The Movie Database (TMDB).

The TV's EPG gives a programme title but no picture, so the title is looked
up on TMDB. Only a near-exact title match is used: news, sport and magazine
programmes usually have no match and simply show no artwork.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api.themoviedb.org/3"
IMAGE_URL = "https://image.tmdb.org/t/p/w780"
TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_CACHE = 500

# EPG decorations that are not part of the title, e.g. "New: Taskmaster",
# "Film: Jaws", "Grand Designs..." (titles cut short end in an ellipsis)
_PREFIX = re.compile(r"^(?:brand\s+new|new|film|movie|premiere|live)\s*:\s*", re.IGNORECASE)
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*$")
_YEAR = re.compile(r"\s*\((\d{4})\)\s*$")


class TmdbAuthError(Exception):
    """TMDB rejected the API key."""


def clean_title(title: str) -> tuple[str, Optional[int]]:
    """Strip EPG decorations from a programme title; returns (title, year or None)."""
    title = _ELLIPSIS.sub("", title.strip())
    title = _PREFIX.sub("", title)
    year = None
    if match := _YEAR.search(title):
        year = int(match.group(1))
        title = title[: match.start()]
    return title.strip(), year


def _fold(title: str) -> str:
    """Comparison form of a title: lower case, "&" as "and", no punctuation or spaces."""
    title = title.casefold().replace("&", "and")
    return re.sub(r"[\W_]+", "", title)


def _year(result: dict[str, Any]) -> Optional[int]:
    date = result.get("first_air_date") or result.get("release_date") or ""
    return int(date[:4]) if date[:4].isdigit() else None


def best_match(results: list[dict[str, Any]], title: str, year: Optional[int]) -> Optional[dict[str, Any]]:
    """The result whose title matches exactly (ignoring case and punctuation).

    TV shows win over films (it's a TV channel), then a matching year, then
    the most popular.
    """
    wanted = _fold(title)
    matches = [
        r for r in results
        if r.get("media_type") in ("tv", "movie")
        and (r.get("backdrop_path") or r.get("poster_path"))
        and wanted in {
            _fold(r.get(key) or "")
            for key in ("name", "original_name", "title", "original_title")
        }
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda r: (
            year is not None and _year(r) == year,
            r["media_type"] == "tv",
            r.get("popularity") or 0,
        ),
    )


class TmdbArtwork:
    """Looks up programme artwork on TMDB, caching results (including misses) per title."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        self._session = async_get_clientsession(hass)
        self._api_key = api_key
        self._cache: dict[str, Optional[str]] = {}
        self._disabled = False

    async def async_validate(self) -> None:
        """Check the API key; raises TmdbAuthError if rejected, aiohttp/timeout errors if unreachable."""
        await self._get("/authentication")

    async def async_lookup(self, title: Optional[str]) -> Optional[str]:
        """Return an image URL for a programme title, or None if there is no confident match."""
        if not title or self._disabled:
            return None
        if title in self._cache:
            return self._cache[title]

        query, year = clean_title(title)
        try:
            data = await self._get(
                "/search/multi",
                query=query, include_adult="false", language="en-GB",
            )
        except TmdbAuthError:
            _LOGGER.warning("TMDB rejected the API key; artwork is off until the key is changed")
            self._disabled = True
            return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            # Not cached: try again when the programme next comes up. The error's
            # text would include the request URL (and so the key): log its type only.
            _LOGGER.debug(
                "TMDB lookup for %r failed: %s %s",
                query, type(err).__name__, getattr(err, "status", ""),
            )
            return None

        match = best_match(data.get("results") or [], query, year)
        url = None
        if match:
            url = IMAGE_URL + (match.get("backdrop_path") or match["poster_path"])
            _LOGGER.debug("TMDB artwork for %r: %s %s", title, match["media_type"], match.get("id"))
        else:
            _LOGGER.debug("No TMDB match for %r", title)

        if len(self._cache) >= MAX_CACHE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[title] = url
        return url

    async def _get(self, path: str, **params: str) -> dict[str, Any]:
        async with self._session.get(
            API_URL + path, params={"api_key": self._api_key, **params}, timeout=TIMEOUT
        ) as resp:
            if resp.status == 401:
                raise TmdbAuthError
            resp.raise_for_status()
            return await resp.json()
