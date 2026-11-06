from types import TracebackType

import httpx

from shinban_sync.models.tmdb import TMDBAlternativeTitles, TMDBSeriesDetails, TMDBTVSearchResult
from shinban_sync.utils.logger import logger


class TMDBProvider:
    def __init__(self, api_token: str):
        self.api_token: str = api_token
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url = "https://api.themoviedb.org/3",
            headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"},
            timeout = 15.0,
        )
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _api_get(
            self, endpoint: str, params: dict[str, str] | None = None
    ) -> dict[str, object] | None:
        if not self.client:
            raise RuntimeError(
                "TMDB Client is not initialized. Please use 'async with TMDBProvider(...) as provider:'"
            )

        try:
            resp = await self.client.get(url = endpoint, params = params)
            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"TMDB [Errno {e.response.status_code}] Req: {endpoint} -> {e.response.text}"
            )
        except httpx.HTTPError as e:
            logger.error(f"TMDB request failed: {e}")

        return None

    async def search_tv(self, query: str, language: str = "zh-CN") -> TMDBTVSearchResult | None:
        data = await self._api_get("/search/tv", {"query": query, "language": language})
        if not data:
            return None

        try:
            return TMDBTVSearchResult.from_json(data)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to parse TMDB search result: {e}")

    async def get_series_details(
            self, series_id: int, language: str = "zh-CN"
    ) -> TMDBSeriesDetails | None:
        data = await self._api_get(f"/tv/{series_id}", {"language": language})
        if not data:
            return None

        try:
            return TMDBSeriesDetails.from_json(data)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to parse TMDB series (ID:{series_id}): {e}")

    async def get_alternative_titles(self, series_id: int) -> TMDBAlternativeTitles | None:
        data = await self._api_get(f"/tv/{series_id}/alternative_titles")
        if not data:
            return None

        try:
            return TMDBAlternativeTitles.from_json(data)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to parse TMDB alternative titles (ID:{series_id}): {e}")
