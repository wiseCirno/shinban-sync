import asyncio
import base64

import httpx
from fake_useragent import UserAgent
from httpx import AsyncClient, HTTPStatusError

from src.shinban_sync.core.logger import logger
from src.shinban_sync.models.config import Aria2Config


class Aria2Downloader:
    def __init__(self, config: Aria2Config):
        self._config = config
        self._client = AsyncClient(headers = {"User-Agent": UserAgent().random}, timeout = 10.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    async def _rpc_call(self, method: str, params: list, task_id: str = "bot"):
        token_str = self._config.token
        if not token_str.startswith("token:"):
            token_str = f"token:{token_str}"

        payload = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": method,
            "params": [token_str] + params
        }

        try:
            response = await self._client.post(self._config.base_url, json = payload)
            response.raise_for_status()
            json_resp = response.json()
            if "error" in json_resp:
                logger.error(f"Aria2 RPC 错误: {json_resp['error']}")
                return None
            return json_resp
        except HTTPStatusError as e:
            logger.error(f"Aria2 异常状态码: {e}")
        except httpx.RemoteProtocolError as e:
            logger.error(f"Aria2 远程协议错误: {e}")
        except Exception as e:
            logger.error(f"Aria2 未知错误: {e}")

    async def add_torrent(self, torrent_url: str, task_name: str, allow_override: bool = False) -> str:
        """
        :param torrent_url: 种子链接
        :param task_name: 任务名称
        :param allow_override: 是否允许覆盖本地同名文件
        :return: Aria2 任务 Gid
        """
        torrent_raw = await self._client.get(torrent_url)
        torrent_raw.raise_for_status()
        torrent_b64 = base64.b64encode(torrent_raw.content).decode('utf-8')

        # 防止意外状况出现视频下载下来以后又触发了一次下载，这里先直接处理为覆盖原文件
        options = {
            "allow-overwrite": "true" if allow_override else "false"
        }

        resp = await self._rpc_call("aria2.addTorrent", [torrent_b64, [], options], task_name)
        return resp["result"] if resp else ""

    async def wait_for_completion(self, gid: str) -> str | None:
        while True:
            resp = await self._rpc_call("aria2.tellStatus", [gid, ["status", "dir", "bittorrent"]])
            if resp:
                status = resp["result"]
                if status["status"] == "complete":
                    name = status.get("bittorrent", {}).get("info", {}).get("name", "")
                    return name
                elif status["status"] in ["error", "removed"]:
                    logger.error(f"Aria2 任务返回 {status["status"]}")
                    return None

            await asyncio.sleep(60)  # 一分钟间隔够了，种子一般下的也不快
