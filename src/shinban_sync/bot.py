import asyncio
from datetime import datetime, timezone
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, CommandHandler

from src.shinban_sync.core.config import ConfigManager
from src.shinban_sync.core.logger import logger
from src.shinban_sync.metadata.acg_rip import AcgRipProvider
from src.shinban_sync.metadata.tmdb import TMDBProvider
from src.shinban_sync.models.bangumi import BangumiInfo
from src.shinban_sync.models.tmdb import TMDBTVSearchItem, TMDBSeason, TMDBSeriesDetails


class Bot:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.tmdb_provider = TMDBProvider(config.get_tmdb_token())

        self.app = Application.builder().token(config.get_telegram_bot_token()).build()
        self.app.add_handler(CommandHandler("subscribe", self.subscribe_command))
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

        return InlineKeyboardMarkup([nav_row, [InlineKeyboardButton("确定", callback_data = "tv_confirm")]])

    @staticmethod
    def _build_season_keyboard(seasons: List[TMDBSeason]) -> InlineKeyboardMarkup:
        keyboard = []
        for i, season in enumerate(seasons):
            if season.season_number == 0:
                continue

            keyboard.append([InlineKeyboardButton(f"{season.name}", callback_data = f"season_sel_{i}")])

        keyboard.append([InlineKeyboardButton("返回", callback_data = "tv_back")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _build_subtitle_keyboard(groups: List[str], page: int) -> InlineKeyboardMarkup:
        per_page = 8
        total_pages = (len(groups) + per_page - 1) // per_page
        start_idx = page * per_page
        end_idx = start_idx + per_page
        current_groups = groups[start_idx:end_idx]

        keyboard = []
        row = []
        for i, group in enumerate(current_groups):
            global_idx = start_idx + i
            row.append(InlineKeyboardButton(f"{group}", callback_data = f"grp_sel_{global_idx}"))
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
    def _get_image_url(path: str, is_backdrop: bool = True) -> str:
        if not path:
            return "https://placehold.co/1280x720/222222/FFFFFF.png?text=No+Image"

        size = "w1280" if is_backdrop else "w780"
        return f"https://image.tmdb.org/t/p/{size}{path}"

    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.from_user.id == int(self.config.get_telegram_user_id()):
            await update.message.reply_text("You are not allowed to use this command.")
            return

        if not context.args:
            await update.message.reply_text("缺少搜索关键字，用例：`/subscribe [番剧名称]`")
            return

        query = " ".join(context.args)
        loading_msg = await update.message.reply_text("请稍候...", parse_mode = "HTML")

        async with self.tmdb_provider as tmdb:
            search_res = await tmdb.search_tv(query)

        if not search_res or not search_res.results:
            await loading_msg.edit_text("❌ <b>未能找到相关剧集</b>", parse_mode = "HTML")
            return

        context.user_data['tmdb_results'] = search_res.results
        context.user_data['current_tv_index'] = 0

        item = search_res.results[0]
        await loading_msg.delete()
        await update.message.reply_photo(
            photo = self._get_image_url(item.backdrop_path),
            caption = self._build_tv_text(item),
            parse_mode = "HTML",
            reply_markup = self._build_tv_keyboard(0, len(search_res.results))
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        await query.answer()

        tmdb_results = context.user_data.get('tmdb_results')
        if not tmdb_results:
            await query.edit_message_caption("会话已过期，请重新搜索")
            return

        tv_idx = context.user_data.get('current_tv_index', 0)
        tmdb_result = tmdb_results[tv_idx]

        # TMDB 搜索翻页
        if data in ("tv_prev", "tv_next", "tv_back"):
            if data == "tv_prev":
                tv_idx = max(0, tv_idx - 1)
            elif data == "tv_next":
                tv_idx = min(len(tmdb_results) - 1, tv_idx + 1)

            context.user_data['current_tv_index'] = tv_idx
            new_item = tmdb_results[tv_idx]
            await query.edit_message_media(
                media = InputMediaPhoto(media = self._get_image_url(new_item.backdrop_path),
                                        caption = self._build_tv_text(new_item), parse_mode = "HTML"),
                reply_markup = self._build_tv_keyboard(tv_idx, len(tmdb_results))
            )

        elif data == "tv_confirm":
            await query.edit_message_caption("获取系列详情...", parse_mode = "HTML")

            async with self.tmdb_provider as tmdb:
                details: TMDBSeriesDetails = await tmdb.get_series_details(tmdb_result.id)

            if not details or not details.seasons:
                await query.edit_message_caption("❌ 获取系列详情失败或没有可用季")
                return

            context.user_data['seasons'] = details.seasons
            await query.edit_message_caption(
                caption = f"<b>已选择：{tmdb_result.name}</b>\n\n👇 请选择要下载的季度：",
                parse_mode = "HTML",
                reply_markup = self._build_season_keyboard(details.seasons))

        elif data.startswith("season_sel_"):
            await query.edit_message_caption("获取可用字幕组...", parse_mode = "HTML")

            season_idx = int(data.split("_")[-1])
            season: TMDBSeason = context.user_data['seasons'][season_idx]
            context.user_data['selected_season'] = season

            async with self.tmdb_provider as tmdb:
                alt_titles = await tmdb.get_alternative_titles(tmdb_result.id)

            search_keywords = [tmdb_result.name, tmdb_result.original_name]
            if alt_titles:
                cn_tw_titles = alt_titles.get_titles_by_country(["CN", "TW"])
                search_keywords.extend(cn_tw_titles)

            search_keywords: List[str] = list(dict.fromkeys(search_keywords))[:3]
            search_keywords = [s.replace('-', '') for s in search_keywords]  # 神秘bug,搜索内容包含'-'会502

            bangumi_results = []
            async with AcgRipProvider() as acg:
                tasks = [acg.search(kw) for kw in search_keywords]
                res_list = await asyncio.gather(*tasks)
                for res in res_list:
                    bangumi_results.extend(res)

            unique_bangumi = {}
            season_date = None
            if season.air_date:
                try:
                    season_date = datetime.strptime(season.air_date, "%Y-%m-%d").replace(tzinfo = timezone.utc)
                except ValueError:
                    pass

            for result in bangumi_results:
                if result.group is None:
                    continue
                if season_date is None:
                    continue
                if season_date and result.pub_date < season_date:
                    continue
                if result.link not in unique_bangumi:
                    unique_bangumi[result.link] = result

            processed_bangumi = list(unique_bangumi.values())
            if not processed_bangumi:
                await query.edit_message_caption(
                    caption = "<b>在 ACG.RIP. 中未找到匹配该季的有效资源</b>",
                    parse_mode = "HTML",
                    reply_markup = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("返回", callback_data = "tv_confirm")]])
                )
                return

            available_groups = list({b.group for b in processed_bangumi})
            context.user_data['acg_results'] = processed_bangumi
            context.user_data['available_groups'] = available_groups

            await query.edit_message_media(
                media = InputMediaPhoto(media = self._get_image_url(season.poster_path, is_backdrop = False),
                                        caption = f"<b>已选择：{season.name}</b>\n\n👇 请选择字幕组：",
                                        parse_mode = "HTML"),
                reply_markup = self._build_subtitle_keyboard(available_groups, page = 0)
            )

        elif data.startswith("grp_page_"):
            page = int(data.split("_")[-1])
            available_groups = context.user_data['available_groups']
            await query.edit_message_reply_markup(self._build_subtitle_keyboard(available_groups, page))

        elif data.startswith("grp_sel_"):
            group_idx = int(data.split("_")[-1])

            available_groups = context.user_data['available_groups']
            acg_results = context.user_data['acg_results']
            tmdb_results = context.user_data['tmdb_results']
            tv_idx = context.user_data.get('current_tv_index', 0)

            tmdb_result = tmdb_results[tv_idx]
            season = context.user_data['selected_season']
            selected_group = available_groups[group_idx]

            group_items = [result for result in acg_results if result.group == selected_group]
            target_bangumi: BangumiInfo = group_items[0]

            # 容错处理：部分未开播剧集首播日期可能为空
            first_air_date = tmdb_result.first_air_date if tmdb_result.first_air_date else "2000-01-01"
            season_air_date = season.air_date if season.air_date else first_air_date

            # 构建符合最新 BangumiConfig 定义的字典
            new_anime_dict = {
                "search_keyword": target_bangumi.titles[0],
                "filename": tmdb_result.original_name,
                "subtitle": selected_group,
                "first_air_date": first_air_date,
                "season_air_date": season_air_date,
                "season": season.season_number,
                "episode_count": season.episode_count,
                "language": target_bangumi.languages[0] if target_bangumi.languages else "chs"
            }

            if self.config.add_anime_config(new_anime_dict):
                await query.edit_message_caption(
                    caption = (
                        f"🎉 <b>已成功添加至订阅列表！</b>\n\n"
                        f"📺 番名：<code>{tmdb_result.original_name}</code>\n"
                        f"🌸 季数：第 {season.season_number} 季\n"
                        f"📝 字幕：{selected_group}"
                    ),
                    parse_mode = "HTML"
                )
            else:
                await query.edit_message_caption(
                    caption = (
                        f"⚠️ <b>添加失败</b>\n\n"
                        f"番剧 <code>{tmdb_result.original_name}</code> 的 第 {season.season_number} 季\n"
                        f"可能已经存在于配置文件中，请勿重复添加。"
                    ),
                    parse_mode = "HTML"
                )

            context.user_data.clear()

    @staticmethod
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        exc = context.error

        if isinstance(exc, (NetworkError, TimedOut)):
            logger.debug(f"Telegram API 网络抖动，正在自动重试... ({exc})")
            return

        logger.error(f"Telegram Bot 发生未捕获的异常: {exc}")

    def run(self):
        self.app.run_polling()
