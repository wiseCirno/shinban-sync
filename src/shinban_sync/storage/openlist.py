import re
import sys
from types import TracebackType
from typing import override

import httpx

from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.config import BangumiConfig, OpenlistStorageConfig
from shinban_sync.storage.base import BaseProvider
from shinban_sync.utils.logger import logger
from shinban_sync.utils.numbers import parse_int


class OpenlistProvider(BaseProvider):
    def __init__(self, storage: OpenlistStorageConfig) -> None:
        super().__init__(storage)
        remote: OpenlistStorageConfig = storage

        self.base_url: str = remote.base_url.rstrip("/")
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        self.client: httpx.Client | None = None

        self._login()

    @override
    def __enter__(self):
        self.client = httpx.Client(timeout = 15.0)
        return super().__enter__()

    @override
    def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        if self.client:
            self.client.close()
        super().__exit__(exc_type, exc_val, exc_tb)

    def _login(self):
        url = f"{self.base_url}/api/auth/login"
        remote = self.storage
        if not isinstance(remote, OpenlistStorageConfig):
            raise TypeError("OpenList 存储配置类型不正确")
        payload = {"username": remote.user, "password": remote.password}

        try:
            with httpx.Client(timeout = 15.0) as temp_client:
                resp = temp_client.post(url, json = payload)
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 200:
                    raise ValueError(f"Login failed: {data.get('message')}")

                token = data.get("data", {}).get("token")
                if not token:
                    raise ValueError("Invalid token")

                self.headers["Authorization"] = token

        except httpx.HTTPError as e:
            logger.error(f"Openlist 请求失败: {e}")
            sys.exit(1)
        except (TypeError, ValueError, KeyError) as e:
            logger.error(f"Openlist 登录响应无法解析: {e}")
            sys.exit(1)

    def _api_post(
            self, endpoint: str, json_data: dict[str, object], suppress_error: bool = False
    ) -> object | None:
        if not self.client:
            raise RuntimeError(
                "Openlist Client is not initialized. Please use 'async with OpenlistProvider(...) as provider:' "
            )

        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.client.post(url, headers = self.headers, json = json_data)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            if not suppress_error:
                logger.error(f"OpenList 网络请求异常 {endpoint}: {e}")
            raise OSError(f"网络异常: {e}") from e

        if not isinstance(payload, dict):
            raise OSError("OpenList 返回的不是对象")
        code = payload.get("code")
        message = payload.get("message", "")
        message_text = message.lower() if isinstance(message, str) else ""
        if code != 200:
            if "not found" in message_text or "not exist" in message_text or code == 404:
                return None

            if not suppress_error:
                logger.error(f"OpenList 状态码错误 ({endpoint}): {message}")
            raise OSError(f"API异常: {message}")

        data = payload

        result = data.get("data")
        return result if result is not None else True

    def _makedirs(self, path: str):
        folders = path.replace("\\", "/").strip("/").split("/")
        current_path = ""
        for folder in folders:
            if not folder:
                continue
            current_path += f"/{folder}"

            try:
                res = self._api_post("/api/fs/get", {"path": current_path}, suppress_error = True)
                if not res:
                    self._api_post("/api/fs/mkdir", {"path": current_path}, suppress_error = True)
            except OSError:
                pass

    def _rename(self, path: str, new_name: str) -> bool:
        try:
            res = self._api_post("/api/fs/rename", {"path": path, "name": new_name})
            return res is not None
        except OSError:
            return False

    def _move(self, src_dir: str, dst_dir: str, file_name: str) -> bool:
        try:
            res = self._api_post(
                "/api/fs/move", {"src_dir": src_dir, "dst_dir": dst_dir, "names": [file_name]}
            )
            return res is not None
        except OSError:
            return False

    @override
    def rename_and_move_bangumi(
            self, info: BangumiInfo, config: BangumiConfig, file_name: str
    ) -> str:
        src_dir = self.storage.aria2_path.rstrip("/")
        src_path = f"{src_dir}/{file_name}"
        target_dir = self.get_target_dir(config).rstrip("/")
        self._makedirs(target_dir)

        new_filename = self.get_standardized_filename(info, config, file_name)
        if not self._rename(src_path, new_filename):
            raise OSError(f"Cannot rename file {file_name}")

        if not self._move(src_dir, target_dir, new_filename):
            raise OSError(f"Cannot move file {file_name}")

        return f"{target_dir}/{new_filename}"

    @override
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        target_dir = self.get_target_dir(config)

        try:
            res = self._api_post(
                "/api/fs/list",
                {"path": target_dir, "page": 1, "per_page": 1000},
                suppress_error = True,
            )
            if not isinstance(res, dict):
                return []

            contents = res.get("content") or []
            if not isinstance(contents, list):
                return []
            matches: list[int] = []
            for item in contents:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                if not isinstance(name, str):
                    continue
                found = re.search(r"S\d+E(\d+)", name)
                if found is not None:
                    matches.append(parse_int(found.group(1)))

            return matches
        except OSError as e:
            logger.warning(f"获取 {config.filename} 进度失败，暂时跳过。原因: {e}")
            return []
