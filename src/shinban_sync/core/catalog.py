import asyncio
from datetime import UTC, datetime
from typing import Any

from shinban_sync.metadata.acg_rip import AcgRipProvider
from shinban_sync.metadata.tmdb import TMDBProvider
from shinban_sync.models.bangumi import BangumiInfo, SubtitleGroup
from shinban_sync.models.tmdb import TMDBTVSearchItem
from shinban_sync.utils.numbers import parse_float, parse_int


def subtitle_names() -> list[str]:
    return list(SubtitleGroup.__members__.keys())


def _poster(path: str | None, backdrop: bool = False) -> str | None:
    if not path:
        return None
    size = "w1280" if backdrop else "w342"
    return f"https://image.tmdb.org/t/p/{size}{path}"


def _show_dict(item: TMDBTVSearchItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "original_name": item.original_name,
        "overview": item.overview or "",
        "first_air_date": item.first_air_date or "",
        "popularity": item.popularity,
        "vote_average": item.vote_average,
        "poster_url": _poster(item.poster_path),
        "backdrop_url": _poster(item.backdrop_path, backdrop = True),
    }


async def search_tv(token: str, query: str) -> list[dict[str, Any]]:
    async with TMDBProvider(token) as tmdb:
        result = await tmdb.search_tv(query)
    if not result or not result.results:
        return []
    return [_show_dict(item) for item in result.results]


async def series_detail(token: str, series_id: int) -> dict[str, Any] | None:
    async with TMDBProvider(token) as tmdb:
        details = await tmdb.get_series_details(series_id)
    if not details:
        return None
    seasons = []
    for season in details.seasons:
        if season.season_number == 0:
            continue
        seasons.append(
            {
                "season_number": season.season_number,
                "name": season.name,
                "overview": season.overview or "",
                "episode_count": season.episode_count,
                "air_date": season.air_date or "",
                "poster_url": _poster(season.poster_path),
            }
        )
    return {
        "id": details.id,
        "name": details.name,
        "original_name": details.original_name,
        "overview": details.overview or "",
        "first_air_date": details.first_air_date or "",
        "poster_url": _poster(details.poster_path),
        "backdrop_url": _poster(details.backdrop_path, backdrop = True),
        "seasons": seasons,
    }


async def _alternative_titles(token: str, series_id: int) -> list[str]:
    async with TMDBProvider(token) as tmdb:
        alt = await tmdb.get_alternative_titles(series_id)
    if not alt:
        return []
    return alt.get_titles_by_country(["CN", "TW"])


async def discover_groups(token: str, series_id: int, season_number: int) -> dict[str, Any]:
    detail = await series_detail(token, series_id)
    if not detail:
        raise RuntimeError("获取系列详情失败")
    season = next(
        (item for item in detail["seasons"] if item["season_number"] == season_number), None
    )
    if season is None:
        raise RuntimeError(f"没有第 {season_number} 季")

    alt_titles = await _alternative_titles(token, series_id)
    keywords = [detail["name"], detail["original_name"], *alt_titles]
    keywords = list(dict.fromkeys(kw.replace("-", "") for kw in keywords if kw))[:3]

    bangumi_results: list[BangumiInfo] = []
    async with AcgRipProvider() as acg:
        batches = await asyncio.gather(*[acg.search(kw) for kw in keywords])
    for batch in batches:
        bangumi_results.extend(batch)

    season_date = None
    if season["air_date"]:
        try:
            season_date = datetime.strptime(season["air_date"], "%Y-%m-%d").replace(tzinfo = UTC)
        except ValueError:
            season_date = None

    unique: dict[str, BangumiInfo] = {}
    for result in bangumi_results:
        if not result.group or result.group not in SubtitleGroup.__members__:
            continue
        if season_date is None or result.pub_date < season_date:
            continue
        unique.setdefault(result.link, result)

    grouped: dict[str, list[BangumiInfo]] = {}
    for item in unique.values():
        if not item.group:
            continue
        grouped.setdefault(item.group, []).append(item)

    groups = []
    for name, items in grouped.items():
        episodes = []
        for item in items:
            try:
                episodes.append(parse_float(item.episode))
            except ValueError:
                continue
        latest = max(episodes) if episodes else None
        sample = items[0]
        groups.append(
            {
                "name": name,
                "latest_episode": parse_int(latest)
                if latest is not None and latest.is_integer()
                else latest,
                "language": sample.languages[0] if sample.languages else "chs",
                "search_keyword": sample.titles[0] if sample.titles else detail["name"],
            }
        )
    groups.sort(
        key = lambda item: (
            item["latest_episode"] is None,
            -(item["latest_episode"] or 0),
            item["name"],
        )
    )
    return {"series": detail, "season": season, "groups": groups}


def subscription_from_discovery(discovered: dict[str, Any], subtitle: str) -> dict[str, Any]:
    matched = next((item for item in discovered["groups"] if item["name"] == subtitle), None)
    if matched is None:
        raise RuntimeError(f"字幕组不在检索结果中: {subtitle}")
    series = discovered["series"]
    season = discovered["season"]
    first_air_date = series["first_air_date"] or "2000-01-01"
    season_air_date = season["air_date"] or first_air_date
    return {
        "title": series.get("name") or matched["search_keyword"],
        "search_keyword": matched["search_keyword"],
        "filename": series["original_name"],
        "subtitle": subtitle,
        "first_air_date": first_air_date,
        "season_air_date": season_air_date,
        "season": season["season_number"],
        "episode_count": season["episode_count"] or 12,
        "language": matched["language"] or "chs",
    }
