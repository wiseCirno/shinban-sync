import asyncio
from datetime import datetime, timedelta

import httpx

from shinban_sync.core.config import ConfigManager
from shinban_sync.downloader.aria2 import Aria2Downloader
from shinban_sync.metadata.acg_rip import AcgRipProvider
from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.config import (
    BangumiConfig,
    LocalStorageConfig,
    OpenlistStorageConfig,
    SftpStorageConfig,
)
from shinban_sync.storage.base import BaseProvider
from shinban_sync.utils.logger import logger
from shinban_sync.utils.numbers import parse_float, parse_int

StorageConfig = LocalStorageConfig | OpenlistStorageConfig | SftpStorageConfig


def get_provider(storage_config: StorageConfig) -> BaseProvider:
    if isinstance(storage_config, SftpStorageConfig):
        from shinban_sync.storage.sftp import SftpProvider

        return SftpProvider(storage_config)
    if isinstance(storage_config, LocalStorageConfig):
        from shinban_sync.storage.local import LocalProvider

        return LocalProvider(storage_config)
    from shinban_sync.storage.openlist import OpenlistProvider

    return OpenlistProvider(storage_config)


async def organize(
        info: BangumiInfo,
        config: BangumiConfig,
        task: Aria2Downloader,
        manager: BaseProvider,
) -> None:
    display_ep = info.episode[0] if isinstance(info.episode, list) else info.episode
    task_name = f"[{info.pub_date.strftime('%Y-%m-%d')}] {info.titles[0]} - {display_ep}"

    gid = await task.add_torrent(info.torrent, task_name, True)
    if not gid:
        logger.error(f"❌ [下载任务失败] 无法添加 Aria2 任务: {task_name}")
        return

    file_name = await task.wait_for_completion(gid)
    if file_name:
        try:
            result = manager.rename_and_move_bangumi(info, config, file_name)
            logger.info(f"📦 [文件归档] 成功保存至: {result}")
        except OSError as e:
            logger.error(f"❌ [文件操作失败] 发生 IO 错误: {e}")


def _parse_episodes(episode: object) -> list[int]:
    raw_eps = episode if isinstance(episode, list) else [episode]
    parsed = []
    for ep in raw_eps:
        try:
            parsed.append(parse_int(parse_float(ep)))
        except ValueError:
            continue
    return parsed


def _match_items(
        items: list[BangumiInfo],
        anime: BangumiConfig,
        target_name: str,
        missing_episodes: set[int],
        require_language: bool,
) -> list[tuple[BangumiInfo, list[int]]]:
    if not missing_episodes:
        return []

    results: list[tuple[BangumiInfo, list[int]]] = []
    for item in items:
        if not missing_episodes:
            break
        if item.group != anime.subtitle.name:
            continue
        if not any(target_name in t.lower() for t in item.titles):
            continue
        if require_language and anime.language not in item.languages:
            continue

        matched_eps = [ep for ep in _parse_episodes(item.episode) if ep in missing_episodes]
        if not matched_eps:
            continue

        results.append((item, matched_eps))
        missing_episodes.difference_update(matched_eps)

    return results


async def run_once(config_path: str | None = None):
    """检索、下载并归档一轮订阅，然后返回。不保留常驻循环。"""
    config = ConfigManager(config_path)
    storage_config = config.get_storage_config()
    aria2_config = config.get_downloader_config()
    subscribed_anime: list[BangumiConfig] = config.get_anime_configs()

    with get_provider(storage_config) as provider:
        async with Aria2Downloader(aria2_config) as task:
            tasks = []

            for anime in subscribed_anime:
                existing_episodes = set(provider.get_existing_episodes(anime))

                now = (
                    datetime.now(anime.season_air_date.tzinfo)
                    if anime.season_air_date.tzinfo
                    else datetime.now()
                )
                days_since_premiere = (now - anime.season_air_date).days
                if days_since_premiere < 0:
                    logger.info(
                        f"⏳ [尚未开播] 距离《{anime.search_keyword}》开播还有 {-days_since_premiere} 天"
                    )
                    continue

                expected_latest = min(anime.episode_count, (days_since_premiere // 7) + 1)
                missing_episodes = set(range(1, expected_latest + 1)) - existing_episodes

                if not missing_episodes:
                    if len(existing_episodes) >= anime.episode_count:
                        logger.info(f"✨ [全部完结] 《{anime.search_keyword}》所有集数已同步完毕")
                    else:
                        logger.info(f"✨ [进度最新] 《{anime.search_keyword}》已跟上最新进度")
                    continue

                ep_str = ", ".join(str(ep) for ep in sorted(missing_episodes))
                logger.info(f"🔍 [开始检索] 正在寻找《{anime.search_keyword}》第 {ep_str} 集")

                target_name = anime.search_keyword.strip().lower()
                search_term = anime.search_keyword.replace("-", "")
                page = 1

                async with AcgRipProvider() as acg_rip:
                    while missing_episodes:
                        earliest_missing = min(missing_episodes)
                        ideal_date = anime.season_air_date + timedelta(
                            days = 7 * (earliest_missing - 1)
                        )
                        threshold_date = ideal_date - timedelta(days = 7)

                        items: list[BangumiInfo] = await acg_rip.search(search_term, page)
                        if not items:
                            break

                        for item, matched_eps in _match_items(
                                items, anime, target_name, missing_episodes, require_language = True
                        ):
                            tasks.append(organize(item, anime, task, provider))
                            for ep in matched_eps:
                                logger.info(
                                    f"✅ [完美匹配] 发现《{anime.search_keyword}》第 {ep} 集 ({anime.language})"
                                )

                        for item, matched_eps in _match_items(
                                items, anime, target_name, missing_episodes, require_language = False
                        ):
                            tasks.append(organize(item, anime, task, provider))
                            langs_str = "/".join(item.languages) if item.languages else "未指定"
                            for ep in matched_eps:
                                logger.info(
                                    f"✅ [宽松匹配] 发现《{anime.search_keyword}》第 {ep} 集 (语言: {langs_str})"
                                )

                        if not missing_episodes:
                            break

                        if items[-1].pub_date.timestamp() < threshold_date.timestamp():
                            break

                        page += 1

                if missing_episodes:
                    remaining_str = ", ".join(str(ep) for ep in sorted(missing_episodes))
                    logger.info(
                        f"⚠️ [等待发布] 字幕组 [{anime.subtitle.name}] 尚未发布《{anime.search_keyword}》第 {remaining_str} 集"
                    )

            if tasks:
                await asyncio.gather(*tasks)


def check_network_connectivity() -> bool:
    try:
        with httpx.Client(timeout = 5.0) as client:
            client.head("https://acg.rip")
        return True
    except httpx.RequestError:
        return False
