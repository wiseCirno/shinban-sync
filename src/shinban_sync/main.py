import argparse
import asyncio
import os
from datetime import datetime, timedelta
from typing import List

import httpx

from src.shinban_sync.bot import Bot
from src.shinban_sync.core.config import ConfigManager, logger
from src.shinban_sync.downloader.aria2 import Aria2Downloader
from src.shinban_sync.metadata.acg_rip import AcgRipProvider
from src.shinban_sync.models.bangumi import BangumiInfo
from src.shinban_sync.models.config import BangumiConfig
from src.shinban_sync.storage.base import BaseProvider


def get_provider(storage_config) -> BaseProvider:
    if not storage_config or not getattr(storage_config, 'provider', None):
        logger.error("请在 config.yml 中配置 provider")
        exit(1)

    provider_type = storage_config.provider.lower()
    if provider_type == "sftp":
        from src.shinban_sync.storage.sftp import SftpProvider
        return SftpProvider(storage_config)
    elif provider_type == "local":
        from src.shinban_sync.storage.local import LocalProvider
        return LocalProvider(storage_config)
    elif provider_type == "openlist":
        from src.shinban_sync.storage.openlist import OpenlistProvider
        return OpenlistProvider(storage_config)

    logger.error(f"不支持的 Provider 类型: {provider_type}")
    exit(1)


async def organize(info: BangumiInfo, config: BangumiConfig, task: Aria2Downloader, manager: BaseProvider):
    display_ep = info.episode[0] if isinstance(info.episode, list) else info.episode
    task_name = f"[{info.pub_date.strftime('%Y-%m-%d')}] {info.titles[0]} - {display_ep}"

    gid = await task.add_torrent(info.torrent, task_name, True)
    file_name = await task.wait_for_completion(gid)

    if file_name:
        try:
            result = manager.rename_and_move_bangumi(info, config, file_name)
            logger.info(f"文件已保存至 {result}")
        except IOError as e:
            logger.error(e)


async def run_once(config_path: str = None):
    config = ConfigManager(config_path)

    storage_config = config.get_storage_config()
    aria2_config = config.get_downloader_config()
    subscribed_anime: List[BangumiConfig] = config.get_anime_configs()

    with get_provider(storage_config) as provider:
        async with Aria2Downloader(aria2_config) as task:
            tasks = []

            for anime in subscribed_anime:
                latest_episode = provider.get_latest_episode(anime)
                if latest_episode == -1:
                    continue

                now = datetime.now(anime.season_air_date.tzinfo) if anime.season_air_date.tzinfo else datetime.now()
                days_since_premiere = (now - anime.season_air_date).days
                if days_since_premiere < 0:
                    logger.info(f"\"{anime.search_keyword}\"尚未开播 (距离开播还有 {-days_since_premiere} 天)")
                    continue

                expected_latest = min(anime.episode_count, (days_since_premiere // 7) + 1)
                if latest_episode > expected_latest:
                    logger.info(f"\"{anime.search_keyword}\"已跟上最新进度")
                    continue

                missing_episodes = set(range(latest_episode, expected_latest + 1))
                ep_str = ", ".join(str(ep) for ep in sorted(missing_episodes))
                logger.info(f"开始搜索\"{anime.search_keyword}\"第{ep_str}集")

                ideal_date = anime.season_air_date + timedelta(days = 7 * (latest_episode - 1))
                threshold_date = ideal_date - timedelta(days = 7)

                target_name = anime.search_keyword.strip().lower()
                page = 1

                while True:
                    async with AcgRipProvider() as acg_rip:
                        items: List[BangumiInfo] = await acg_rip.get_feed(anime.subtitle, page)
                        if not items:
                            break

                        for item in items:
                            name_match = any(target_name in t.lower() for t in item.titles)
                            lang_match = anime.language in item.languages

                            if not (name_match and lang_match):
                                continue

                            item_eps = item.episode if isinstance(item.episode, list) else [item.episode]
                            matched_eps = []

                            for ep_str_raw in item_eps:
                                try:
                                    ep_int = int(float(ep_str_raw))
                                    if ep_int in missing_episodes:
                                        matched_eps.append(ep_int)
                                except ValueError:
                                    pass

                            if matched_eps:
                                tasks.append(organize(item, anime, task, provider))
                                for ep in matched_eps:
                                    missing_episodes.remove(ep)
                                    logger.info(f"已匹配到\"{anime.search_keyword}\"第{ep}集")

                            if not missing_episodes:
                                break

                    if not missing_episodes:
                        break

                    if items[-1].pub_date.timestamp() < threshold_date.timestamp():
                        remaining_str = ", ".join(str(ep) for ep in sorted(missing_episodes))
                        logger.info(f"<{anime.subtitle.name}>尚未发布\"{anime.search_keyword}\"第{remaining_str}集")
                        break

                    page += 1

            if tasks:
                await asyncio.gather(*tasks)


def parse_args():
    parser = argparse.ArgumentParser(description = "ShinbanSync - 新番同步")

    parser.add_argument('-l', '--loop', action = 'store_true',
                        help = '持续运行直到用户中断')

    parser.add_argument('-i', '--interval', type = int, metavar = '',
                        help = '循环间隔时间 (sec)，未指定时为 86400')

    parser.add_argument('-c', '--config', type = str, metavar = '',
                        help = '配置文件路径，未指定时在默认路径中寻找 config.yml')

    parser.add_argument('-b', '--bot', action = 'store_true',
                        help = '启用 Telegram Bot')

    args = parser.parse_args()

    if args.interval is not None and not args.loop:
        parser.error("参数错误: -i/--interval 必须配合 -l/--loop 一起使用")

    return args


async def scraping_loop(config_path: str, interval: int):
    while True:
        await run_once(config_path)
        logger.info(f"下一次检索将在 {interval} 秒后进行")
        await asyncio.sleep(interval)


async def async_main():
    args = parse_args()
    env_bot_flag = os.getenv("ENABLE_TELEGRAM_BOT", "").strip().lower() in ["true", "1", "yes"]

    if args.bot or env_bot_flag:
        logger.info("正在启动 Telegram Bot...")
        bot = Bot(ConfigManager(args.config))

        await bot.app.initialize()
        await bot.app.start()
        await bot.app.updater.start_polling()
        logger.info("Telegram Bot 已成功启用")

        try:
            if args.loop:
                interval = args.interval if args.interval is not None else 86400
                logger.info(f"启动检索循环模式，间隔 {interval} 秒")
                await scraping_loop(args.config, interval)
            else:
                stop_event = asyncio.Event()
                await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("正在关闭 Telegram Bot...")
            await bot.app.updater.stop()
            await bot.app.stop()
            await bot.app.shutdown()

    elif args.loop:
        interval = args.interval if args.interval is not None else 86400
        logger.info(f"启动检索循环模式，间隔 {interval} 秒")
        await scraping_loop(args.config, interval)

    else:
        await run_once(args.config)


def check_network_connectivity() -> bool:
    try:
        with httpx.Client(timeout = 5.0) as client:
            client.head("https://acg.rip")
        return True
    except httpx.RequestError:
        return False


if __name__ == "__main__":
    if not check_network_connectivity():
        logger.error(":( 无法访问到服务接口，请检查一下网络或代理设置")
        exit(1)

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("用户主动中断 (Ctrl+C)")
        exit(0)
