import re
from datetime import datetime
from typing import List, Optional
from xml.etree import ElementTree

import httpx
from fake_useragent import UserAgent

from src.shinban_sync.core.acg_rip_rate_limit import request_acg_rip
from src.shinban_sync.core.logger import logger
from src.shinban_sync.models.bangumi import BangumiInfo, SubtitleGroup


class AcgRipProvider:
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            headers = {
                "User-Agent": UserAgent().random
            },
            timeout = 15.0
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _fetch_xml_raw(self, url: str) -> Optional[str]:
        if not self.client:
            raise RuntimeError(
                "AcgRipProvider Client is not initialized. Please use 'async with AcgRipProvider() as provider:'")

        try:
            resp = await request_acg_rip(self.client, "GET", url)
            resp.raise_for_status()
            return resp.text

        except httpx.ReadTimeout as e:
            logger.error(f"AcgRip request timed out: {e}, url: {url}")
        except httpx.HTTPStatusError as e:
            logger.error(f"AcgRip [Errno {e.response.status_code}] Req: {url} -> {e.response.text}")
        except Exception as e:
            logger.error(f"AcgRip request failed: {e}")

        return None

    @staticmethod
    def _extract_group(raw: str) -> SubtitleGroup | None:
        for name, group in SubtitleGroup.__members__.items():
            if name in raw:
                return group
        return None

    @staticmethod
    def _extract_titles(raw: str) -> list[str]:
        clean_title = raw

        # 找单集截断点，如 " - 01"
        single_dash = list(re.finditer(r'\s+-\s+第?\d+', clean_title))
        if single_dash:
            clean_title = clean_title[:single_dash[-1].start()]
        else:
            # 找紧贴标题的括号集数，如 "[01]", "[01v2]", "[第01话]", "[01-12]"
            bracket_ep = list(
                re.finditer(r'\[第?\d{1,3}(?:\.\d+)?(?:v\d+)?[话話集]?(?:-\d{1,3})?(?:\s*(?:END|Fin|完.*))?]',
                            clean_title, re.IGNORECASE))
            if bracket_ep:
                clean_title = clean_title[:bracket_ep[-1].start()]
            else:
                # 如果完全没有集数，找带有视频规格的标签作为截断点
                tag_match = re.search(r'\s*\[(?=.*(?:1080p|720p|WebRip|BDRip|x264|HEVC))', clean_title, re.IGNORECASE)
                if tag_match:
                    clean_title = clean_title[:tag_match.start()]

        # 剥离开头的字幕组和宣传标语
        while True:
            new_title = clean_title
            # 匹配以 【】、★ ★、[] 包裹的开头
            for pattern in [r'^【.*?】\s*', r'^★.*?★\s*', r'^\[.*?\]\s*']:
                temp = re.sub(pattern, '', new_title)
                if temp.strip():
                    new_title = temp

            if new_title == clean_title:
                break
            clean_title = new_title

        # 清理首尾可能包裹着标题的残留外壳括号
        clean_title = clean_title.strip()
        if clean_title.startswith('[') and clean_title.endswith(']'):
            clean_title = clean_title[1:-1]

        # 分割多语言标题
        return [t.strip() for t in clean_title.split('/') if t.strip()]

    @staticmethod
    def _extract_episode(raw: str) -> list[str] | str | None:
        # 匹配合集模式: [01-12] 或[第01-12话]
        batch_match = re.search(r'\[第?(\d{1,3})-(\d{1,3})[^]]*]', raw)
        if batch_match:
            start = int(batch_match.group(1))
            end = int(batch_match.group(2))
            return [str(i) for i in range(start, end + 1)]

        # 匹配单集模式 A: " - 01", " 第08.5话 "
        single_dash = list(re.finditer(r'\s+-\s+第?(\d+(?:\.\d+)?)(?:v\d+)?[话話集]?', raw))
        if single_dash:
            ep_str = single_dash[-1].group(1)
            num = float(ep_str)
            return str(int(num)) if num.is_integer() else str(num)

        # 匹配单集模式 B: [01], [01v2], [01 END], [第01话]
        bracket_ep = list(
            re.finditer(r'\[第?(\d{1,3}(?:\.\d+)?)(?:v\d+)?[话話集]?(?:\s*(?:END|Fin|完.*))?]', raw,
                        re.IGNORECASE))
        if bracket_ep:
            ep_str = bracket_ep[-1].group(1)
            num = float(ep_str)
            return str(int(num)) if num.is_integer() else str(num)

        return None

    @staticmethod
    def _extract_language(raw: str) -> list[str]:
        brackets = re.findall(r'\[(.*?)]', raw)

        if len(brackets) > 1:
            meta_text = "".join(brackets[1:])
        else:
            meta_text = "".join(brackets) if brackets else raw

        langs = []
        if "简" in meta_text:
            langs.append("chs")
        if "繁" in meta_text:
            langs.append("cht")
        if "日" in meta_text:
            langs.append("jp")

        return langs

    def _extract_bangumi_items(self, raw: str) -> list[BangumiInfo]:
        items: List[BangumiInfo] = []
        try:
            root = ElementTree.fromstring(raw)
            for item in root.findall(".//item"):
                raw_title = item.findtext("title", default = "")
                raw_date = item.findtext("pubDate", default = "")

                enclosure = item.find("enclosure")
                if enclosure is None:
                    continue

                episode = self._extract_episode(raw_title)
                if episode is None or isinstance(episode, list):
                    continue

                titles = self._extract_titles(raw_title)
                pub_date = datetime.strptime(raw_date, "%a, %d %b %Y %H:%M:%S %z")
                languages = self._extract_language(raw_title)
                link = item.findtext("link", default = "")
                torrent = enclosure.attrib.get("url", "")
                group = self._extract_group(raw_title)

                items.append(
                    BangumiInfo(
                        titles = titles,
                        episode = episode,
                        pub_date = pub_date,
                        languages = languages,
                        link = link,
                        torrent = torrent,
                        group = group.name if group else None
                    )
                )
        except ElementTree.ParseError as e:
            logger.error(f"Failed to parse XML: {e}")

        return items

    async def get_feed(self, provider: SubtitleGroup, page: int) -> List[BangumiInfo]:
        url = f"{provider.value}/page/{page}.xml"
        xml_raw = await self._fetch_xml_raw(url)

        if not xml_raw:
            return []

        return self._extract_bangumi_items(xml_raw)

    async def search(self, term: str) -> List[BangumiInfo]:
        url = f"https://acg.rip/.xml?term={term}"
        xml_raw = await self._fetch_xml_raw(url)

        if not xml_raw:
            return []

        return self._extract_bangumi_items(xml_raw)
