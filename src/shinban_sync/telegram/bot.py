import asyncio
from datetime import UTC, datetime
from typing import Any

from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from shinban_sync.core.config import ConfigManager
from shinban_sync.core.schedule import sync_argv
from shinban_sync.metadata.acg_rip import AcgRipProvider
from shinban_sync.metadata.tmdb import TMDBProvider
from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.tmdb import TMDBSeason, TMDBSeriesDetails, TMDBTVSearchItem
from shinban_sync.utils.logger import logger
from shinban_sync.utils.numbers import parse_int


class Bot:
    def __init__(self, config: ConfigManager):
        self.config: ConfigManager = config
        self.tmdb_provider: TMDBProvider = TMDBProvider(config.get_tmdb_token())
        self.app: Application[Any, Any, Any, Any, Any, Any] = (
            Application.builder().token(config.get_telegram_bot_token()).build()
        )
        self.app.add_handler(CommandHandler("subscribe", self.subscribe_command))
        self.app.add_handler(CommandHandler("refresh", self.refresh_command))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        self.app.add_error_handler(self.error_handler)

    @staticmethod
    def _build_tv_text(item: TMDBTVSearchItem) -> str:
        overview = item.overview if item.overview else "暂无简介"
        overview = overview[:700] + "..." if len(overview) > 700 else overview
        return (
            f"📺 <b>名称：</b>{item.name}\n"
            f"📖 <b>原名：</b>{item.original_name}\n\n"
            f"📝 <b>简介：</b>\n{overview}\n\n"
            f"🔥 <b>热度：</b>{item.popularity:.1f}   |   🌟 <b>评分：</b>{item.vote_average:.1f}\n"
            f"📅 <b>首播：</b>{item.first_air_date}"
        )

    @staticmethod
    def _build_tv_keyboard(index: int, total_items: int) -> InlineKeyboardMarkup:
        nav_row = []
        if index > 0:
            nav_row.append(InlineKeyboardButton("上一个", callback_data = "tv_prev"))
        if index < total_items - 1:
            nav_row.append(InlineKeyboardButton("下一个", callback_data = "tv_next"))
        return InlineKeyboardMarkup(
            [nav_row, [InlineKeyboardButton("确定", callback_data = "tv_confirm")]]
        )

    @staticmethod
    def _build_season_keyboard(seasons: list[TMDBSeason]) -> InlineKeyboardMarkup:
        keyboard = []
        for index, season in enumerate(seasons):
            if season.season_number == 0:
                continue
            keyboard.append(
                [InlineKeyboardButton(season.name, callback_data = f"season_sel_{index}")]
            )
        keyboard.append([InlineKeyboardButton("返回", callback_data = "tv_back")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _build_subtitle_keyboard(groups: list[str], page: int) -> InlineKeyboardMarkup:
        per_page = 8
        total_pages = (len(groups) + per_page - 1) // per_page
        start_idx = page * per_page
        current_groups = groups[start_idx: start_idx + per_page]
        keyboard = []
        row = []
        for offset, group in enumerate(current_groups):
            row.append(InlineKeyboardButton(group, callback_data = f"grp_sel_{start_idx + offset}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("上一页", callback_data = f"grp_page_{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("下一页", callback_data = f"grp_page_{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _get_image_url(path: str | None, is_backdrop: bool = True) -> str:
        if not path:
            return "https://placehold.co/1280x720/222222/FFFFFF.png?text=No+Image"
        size = "w1280" if is_backdrop else "w780"
        return f"https://image.tmdb.org/t/p/{size}{path}"

    async def _reject(self, update: Update) -> bool:
        user = update.effective_user
        message = update.effective_message
        if user is None or user.id != parse_int(self.config.get_telegram_user_id()):
            if message is not None:
                await message.reply_text("You are not allowed to use this command.")
            return True
        return False

    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await self._reject(update):
            return
        message = update.message
        if message is None:
            return
        if not context.args:
            await message.reply_text("缺少搜索关键字，用例：`/subscribe [番剧名称]`")
            return

        query = " ".join(context.args)
        loading_msg = await message.reply_text("⏳ 请稍候...", parse_mode = "HTML")
        async with self.tmdb_provider as tmdb:
            search_res = await tmdb.search_tv(query)
        if not search_res or not search_res.results:
            await loading_msg.edit_text("❌ <b>未能找到相关剧集</b>", parse_mode = "HTML")
            return

        user_data = context.user_data
        if user_data is None:
            return
        user_data["tmdb_results"] = search_res.results
        user_data["current_tv_index"] = 0
        item = search_res.results[0]
        await loading_msg.delete()
        await message.reply_photo(
            photo = self._get_image_url(item.backdrop_path),
            caption = self._build_tv_text(item),
            parse_mode = "HTML",
            reply_markup = self._build_tv_keyboard(0, len(search_res.results)),
        )

    async def refresh_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        del context
        if await self._reject(update):
            return
        message = update.message
        if message is None:
            return
        await asyncio.create_subprocess_exec(*sync_argv(str(self.config.config_path)))
        await message.reply_text("✅ 已拉起一次同步。检索进程结束后会自行退出。", parse_mode = "HTML")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await self._reject(update):
            return
        query = update.callback_query
        user_data = context.user_data
        if query is None or query.data is None or user_data is None:
            return
        data = query.data
        await query.answer()

        tmdb_results = user_data.get("tmdb_results")
        if not tmdb_results:
            await query.edit_message_caption("会话已过期，请重新搜索")
            return

        tv_idx = parse_int(user_data.get("current_tv_index", 0), 0)
        tmdb_result = tmdb_results[tv_idx]

        if data in ("tv_prev", "tv_next", "tv_back"):
            if data == "tv_prev":
                tv_idx = max(0, tv_idx - 1)
            elif data == "tv_next":
                tv_idx = min(len(tmdb_results) - 1, tv_idx + 1)
            user_data["current_tv_index"] = tv_idx
            new_item = tmdb_results[tv_idx]
            await query.edit_message_media(
                media = InputMediaPhoto(
                    media = self._get_image_url(new_item.backdrop_path),
                    caption = self._build_tv_text(new_item),
                    parse_mode = "HTML",
                ),
                reply_markup = self._build_tv_keyboard(tv_idx, len(tmdb_results)),
            )
            return

        if data == "tv_confirm":
            await query.edit_message_caption("获取系列详情...", parse_mode = "HTML")
            async with self.tmdb_provider as tmdb:
                details: TMDBSeriesDetails | None = await tmdb.get_series_details(tmdb_result.id)
            if not details or not details.seasons:
                await query.edit_message_caption("❌ 获取系列详情失败或没有可用季")
                return
            user_data["seasons"] = details.seasons
            await query.edit_message_caption(
                caption = f"<b>已选择：{tmdb_result.name}</b>\n\n👇 请选择要下载的季度：",
                parse_mode = "HTML",
                reply_markup = self._build_season_keyboard(details.seasons),
            )
            return

        if data.startswith("season_sel_"):
            await self._select_season(query, user_data, tmdb_result, parse_int(data.split("_")[-1]))
            return
        if data.startswith("grp_page_"):
            groups = user_data["available_groups"]
            await query.edit_message_reply_markup(
                self._build_subtitle_keyboard(groups, parse_int(data.split("_")[-1]))
            )
            return
        if data.startswith("grp_sel_"):
            await self._select_group(query, user_data, parse_int(data.split("_")[-1]))

    async def _select_season(
            self,
            query: CallbackQuery,
            user_data: dict[str, Any],
            tmdb_result: TMDBTVSearchItem,
            season_idx: int,
    ) -> None:
        await query.edit_message_caption("获取可用字幕组...", parse_mode = "HTML")
        season: TMDBSeason = user_data["seasons"][season_idx]
        user_data["selected_season"] = season
        async with self.tmdb_provider as tmdb:
            alt_titles = await tmdb.get_alternative_titles(tmdb_result.id)

        search_keywords = [tmdb_result.name, tmdb_result.original_name]
        if alt_titles:
            search_keywords.extend(alt_titles.get_titles_by_country(["CN", "TW"]))
        deduped = list(dict.fromkeys(search_keywords))[:3]
        search_keywords = [item.replace("-", "") for item in deduped]

        bangumi_results: list[BangumiInfo] = []
        async with AcgRipProvider() as acg:
            batches = await asyncio.gather(*[acg.search(keyword) for keyword in search_keywords])
        for batch in batches:
            bangumi_results.extend(batch)

        season_date = None
        if season.air_date:
            try:
                season_date = datetime.strptime(season.air_date, "%Y-%m-%d").replace(tzinfo = UTC)
            except ValueError:
                season_date = None

        unique_bangumi: dict[str, BangumiInfo] = {}
        for result in bangumi_results:
            if result.group is None or season_date is None or result.pub_date < season_date:
                continue
            unique_bangumi.setdefault(result.link, result)

        processed = list(unique_bangumi.values())
        if not processed:
            await query.edit_message_caption(
                caption = "<b>在 ACG.RIP. 中未找到匹配该季的有效资源</b>",
                parse_mode = "HTML",
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("返回", callback_data = "tv_confirm")]]
                ),
            )
            return

        available_groups = list({item.group for item in processed if item.group})
        user_data["acg_results"] = processed
        user_data["available_groups"] = available_groups
        latest: dict[str, float] = {}
        for item in processed:
            if not item.group:
                continue
            try:
                episode = float(item.episode)
            except (TypeError, ValueError):
                continue
            latest[item.group] = max(episode, latest.get(item.group, episode))

        progress = []
        for group in available_groups:
            episode = latest.get(group)
            if episode is None:
                progress.append(f"• <b>{group}</b> : 进度 <b>未知</b>")
            else:
                shown = str(parse_int(episode)) if episode.is_integer() else str(episode)
                progress.append(f"• <b>{group}</b> : 更新到第 <b>{shown}</b> 集")
        caption = (
            f"<b>已选择：{season.name}</b>\n\n"
            f"<b>🚀 发布进度：</b>\n{chr(10).join(progress)}\n\n👇 请选择你要订阅的字幕组："
        )
        await query.edit_message_media(
            media = InputMediaPhoto(
                media = self._get_image_url(season.poster_path, is_backdrop = False),
                caption = caption,
                parse_mode = "HTML",
            ),
            reply_markup = self._build_subtitle_keyboard(available_groups, page = 0),
        )

    async def _select_group(
            self, query: CallbackQuery, user_data: dict[str, Any], group_idx: int
    ) -> None:
        available_groups: list[str] = user_data["available_groups"]
        acg_results: list[BangumiInfo] = user_data["acg_results"]
        tmdb_results: list[TMDBTVSearchItem] = user_data["tmdb_results"]
        tv_idx = parse_int(user_data.get("current_tv_index", 0), 0)
        tmdb_result = tmdb_results[tv_idx]
        season: TMDBSeason = user_data["selected_season"]
        selected_group = available_groups[group_idx]
        group_items = [result for result in acg_results if result.group == selected_group]
        target = group_items[0]
        first_air_date = tmdb_result.first_air_date or "2000-01-01"
        season_air_date = season.air_date or first_air_date
        anime = {
            "title": tmdb_result.name,
            "search_keyword": target.titles[0],
            "filename": tmdb_result.original_name,
            "subtitle": selected_group,
            "first_air_date": first_air_date,
            "season_air_date": season_air_date,
            "season": season.season_number,
            "episode_count": season.episode_count,
            "language": target.languages[0] if target.languages else "chs",
        }
        if self.config.add_anime_config(anime):
            await query.edit_message_caption(
                caption = (
                    "🎉 <b>已成功添加至订阅列表！</b>\n\n"
                    f"📺 番名：<code>{tmdb_result.original_name}</code>\n"
                    f"🌸 季数：第 {season.season_number} 季\n"
                    f"📝 字幕：{selected_group}"
                ),
                parse_mode = "HTML",
            )
        else:
            await query.edit_message_caption(
                caption = (
                    "⚠️ <b>添加失败</b>\n\n"
                    f"番剧 <code>{tmdb_result.original_name}</code> 的 第 {season.season_number} 季\n"
                    "可能已经存在于配置文件中，请勿重复添加。"
                ),
                parse_mode = "HTML",
            )
        user_data.clear()

    @staticmethod
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        del update
        exc = context.error
        if isinstance(exc, (NetworkError, TimedOut)):
            logger.debug(f"Telegram API 网络抖动，正在自动重试... ({exc})")
            return
        logger.error(f"Telegram Bot 发生未捕获的异常: {exc}")
