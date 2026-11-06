import asyncio
import base64
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any

import httpx
from fake_useragent import UserAgent
from httpx import AsyncClient, HTTPStatusError

from shinban_sync.models.config import Aria2Config
from shinban_sync.utils.acg_rip_rate_limit import is_acg_rip_url, request_acg_rip
from shinban_sync.utils.logger import logger
from shinban_sync.utils.numbers import parse_int

# 可复用的任务状态：直接挂到已有 gid，不再重复 addTorrent
_REUSABLE_STATUSES = frozenset({"active", "waiting", "paused", "complete"})


class Aria2Downloader:
    def __init__(self, config: Aria2Config):
        self._config: Aria2Config = config
        self._client: AsyncClient = AsyncClient(
            headers = {"User-Agent": UserAgent().random}, timeout = 10.0
        )
        self._hash_locks: dict[str, asyncio.Lock] = {}
        self._hash_locks_guard: asyncio.Lock = asyncio.Lock()

    async def __aenter__(self):
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def _get_hash_lock(self, info_hash: str) -> asyncio.Lock:
        async with self._hash_locks_guard:
            lock = self._hash_locks.get(info_hash)
            if lock is None:
                lock = asyncio.Lock()
                self._hash_locks[info_hash] = lock
            return lock

    @asynccontextmanager
    async def _hash_mutex(self, info_hash: str | None) -> AsyncGenerator[None]:
        """对同一 info hash 的提交路径加锁；无法解析 hash 时不加锁。"""
        if not info_hash:
            yield
            return
        lock = await self._get_hash_lock(info_hash)
        async with lock:
            yield

    async def _rpc_call(
            self, method: str, params: list[object], task_id: str = "bot"
    ) -> dict[str, Any] | None:
        token_str = self._config.token
        if not token_str.startswith("token:"):
            token_str = f"token:{token_str}"

        payload = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": method,
            "params": [token_str] + params,
        }

        try:
            response = await self._client.post(self._config.base_url, json = payload)
            response.raise_for_status()
            return response.json()
        except HTTPStatusError as e:
            logger.error(f"Aria2 异常状态码: {e}")
        except httpx.RemoteProtocolError as e:
            logger.error(f"Aria2 远程协议错误: {e}")
        except httpx.HTTPError as e:
            logger.error(f"Aria2 未知错误: {e}")
        return None

    @staticmethod
    def _rpc_result(resp: dict[str, Any] | None) -> Any:
        if not resp:
            return None
        if "error" in resp:
            logger.error(f"Aria2 RPC 错误: {resp['error']}")
            return None
        return resp.get("result")

    @staticmethod
    def _build_add_options(allow_override: bool = False) -> dict[str, str]:
        """
        参考 https://aria2.github.io/manual/en/html/aria2c.html#advanced-options

        - allow-overwrite: 无 .aria2 控制文件时允许覆盖已存在文件（EXIT 13）
        - auto-file-renaming: 覆盖模式下关闭自动改名，避免产生 .1 副本
        - remove-control-file + allow-overwrite: 强制从零开始，避免残留控制文件干扰
        - seed-time=0: 下载完成后不做种，尽快变为 complete，减少 info hash 长期占用
        """
        options = {
            "seed-time": "0",
            "allow-overwrite": "true" if allow_override else "false",
            "auto-file-renaming": "false" if allow_override else "true",
        }
        if allow_override:
            options["remove-control-file"] = "true"
        return options

    def _bencode_skip(self, data: bytes, i: int) -> int:
        """跳过一个 bencode 值，返回该值结束后的下标。"""
        if i >= len(data):
            raise ValueError("truncated bencode")

        c = data[i: i + 1]
        if c == b"i":
            return data.index(b"e", i) + 1
        if c in (b"l", b"d"):
            i += 1
            while data[i: i + 1] != b"e":
                i = self._bencode_skip(data, i)
            return i + 1

        colon = data.index(b":", i)
        length = parse_int(data[i:colon])
        return colon + 1 + length

    def _torrent_info_hash(self, torrent_data: bytes) -> str | None:
        """计算 .torrent 的 info hash（SHA-1 十六进制小写）。"""
        marker = b"4:info"
        idx = torrent_data.find(marker)
        if idx < 0:
            return None

        info_start = idx + len(marker)
        try:
            info_end = self._bencode_skip(torrent_data, info_start)
        except (ValueError, IndexError, OverflowError):
            return None

        return hashlib.sha1(torrent_data[info_start:info_end]).hexdigest()

    async def _list_downloads(self, keys: list[str]) -> list[dict[str, Any]]:
        """汇总 active / waiting / stopped 中的任务。"""
        downloads: list[dict[str, Any]] = []

        active = self._rpc_result(await self._rpc_call("aria2.tellActive", [keys]))
        if active:
            downloads.extend(active)

        waiting = self._rpc_result(await self._rpc_call("aria2.tellWaiting", [0, 1000, keys]))
        if waiting:
            downloads.extend(waiting)

        stopped = self._rpc_result(await self._rpc_call("aria2.tellStopped", [0, 1000, keys]))
        if stopped:
            downloads.extend(stopped)

        return downloads

    async def _find_by_info_hash(self, info_hash: str) -> dict[str, Any] | None:
        """按 info hash 查找已有任务"""
        info_hash = info_hash.lower()
        keys = [
            "gid",
            "status",
            "infoHash",
            "errorCode",
            "errorMessage",
            "bittorrent",
            "completedLength",
            "totalLength",
            "seeder",
        ]
        for item in await self._list_downloads(keys):
            item_hash = (item.get("infoHash") or "").lower()
            if item_hash == info_hash:
                return item
        return None

    async def _prepare_hash_slot(self, info_hash: str, task_name: str) -> str:
        """
        在持锁前提下处理同 hash 占用：
        - active / waiting / paused / complete → 返回可复用 gid
        - error / removed → 清除结果，腾出 slot，返回空串
        - 不存在 → 返回空串，允许后续 addTorrent
        """
        existing = await self._find_by_info_hash(info_hash)
        if not existing:
            return ""

        gid = existing["gid"]
        status = existing.get("status", "")

        if status in _REUSABLE_STATUSES:
            logger.info(
                f"♻️ [任务复用] 《{task_name}》info hash 已存在 (gid={gid}, status={status})，复用已有任务"
            )
            return gid

        logger.warning(
            f"⚠️ [清理残留] 《{task_name}》存在失败/已移除的同 hash 任务 (gid={gid}, status={status})，清除后重新提交"
        )
        self._rpc_result(await self._rpc_call("aria2.removeDownloadResult", [gid]))
        return ""

    async def add_torrent(
            self, torrent_url: str, task_name: str, allow_override: bool = False
    ) -> str:
        """
        :param torrent_url: 种子链接
        :param task_name: 任务名称
        :param allow_override: 是否允许覆盖本地同名文件
        :return: Aria2 任务 Gid
        """
        try:
            if is_acg_rip_url(torrent_url):
                torrent_raw = await request_acg_rip(self._client, "GET", torrent_url)
            else:
                torrent_raw = await self._client.get(torrent_url)

            torrent_raw.raise_for_status()
        except HTTPStatusError as e:
            logger.error(f"种子下载失败 [{e.response.status_code}]: {torrent_url}")
            return ""
        except httpx.RequestError as e:
            logger.error(f"种子下载请求失败: {e}, url: {torrent_url}")
            return ""

        torrent_bytes = torrent_raw.content
        torrent_b64 = base64.b64encode(torrent_bytes).decode("utf-8")
        info_hash = self._torrent_info_hash(torrent_bytes)
        options = self._build_add_options(allow_override)

        async with self._hash_mutex(info_hash):
            if info_hash:
                reused = await self._prepare_hash_slot(info_hash, task_name)
                if reused:
                    return reused

            result = self._rpc_result(
                await self._rpc_call("aria2.addTorrent", [torrent_b64, [], options], task_name)
            )
            if result:
                return result

            if info_hash:
                existing = await self._find_by_info_hash(info_hash)
                if existing and existing.get("status") in _REUSABLE_STATUSES:
                    gid = existing["gid"]
                    logger.info(
                        f"♻️ [任务复用] 《{task_name}》提交失败但发现已有任务 (gid={gid}, status={existing.get('status')})，复用"
                    )
                    return gid

            return ""

    @staticmethod
    def _is_download_finished(status: dict[str, Any]) -> bool:
        """判断下载数据是否已完成（BT 做种阶段 status 仍为 active）。"""
        if status.get("status") == "complete":
            return True
        if status.get("status") != "active":
            return False
        # seeder=true 表示本地已完整，正在做种
        if status.get("seeder") == "true":
            return True
        try:
            completed = int(status.get("completedLength") or 0)
            total = int(status.get("totalLength") or 0)
        except (TypeError, ValueError):
            return False
        return 0 < total <= completed

    async def wait_for_completion(self, gid: str) -> str | None:
        keys = [
            "status",
            "dir",
            "bittorrent",
            "completedLength",
            "totalLength",
            "seeder",
            "errorCode",
            "errorMessage",
        ]
        while True:
            resp = await self._rpc_call("aria2.tellStatus", [gid, keys])
            status = self._rpc_result(resp)
            if status:
                if self._is_download_finished(status):
                    return status.get("bittorrent", {}).get("info", {}).get("name", "")

                if status.get("status") in ("error", "removed"):
                    detail = (
                            status.get("errorMessage")
                            or status.get("errorCode")
                            or status.get("status")
                    )
                    logger.error(f"Aria2 任务返回失败: {detail}")
                    return None

            await asyncio.sleep(60)  # 一分钟间隔够了，种子一般下的也不快
