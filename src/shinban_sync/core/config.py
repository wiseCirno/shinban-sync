import os
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from shinban_sync.core.schedule import ScheduleError, friendly_schedule
from shinban_sync.models.config import (
    Aria2Config,
    BangumiConfig,
    LocalStorageConfig,
    OpenlistStorageConfig,
    SftpStorageConfig,
)
from shinban_sync.utils.logger import logger
from shinban_sync.utils.numbers import parse_int

DEFAULT_SCHEDULE_CRON = "0 4 * * *"
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 3325


class ConfigError(RuntimeError):
    """配置缺失或无法解析。调用方决定是退出进程还是返回给界面。"""


class ConfigManager:
    def __init__(self, config_path: str | None = None):
        self.config_path: Path = self._resolve_config_path(config_path)

        try:
            with open(self.config_path, encoding = "utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                raise ConfigError("配置文件根节点必须是映射")
            self.raw_config: dict[str, Any] = loaded
        except yaml.YAMLError as e:
            logger.error(f"配置文件 YAML 格式错误，请检查缩进或语法:\n{e}")
            raise ConfigError(f"配置文件 YAML 格式错误: {e}") from e
        except ConfigError:
            raise
        except (OSError, TypeError) as e:
            logger.error(f"读取配置文件失败: {e}")
            raise ConfigError(f"读取配置文件失败: {e}") from e

    @staticmethod
    def _resolve_config_path(path: str | None = None) -> Path:
        try:
            env_path = os.getenv("BANGUMI_CONFIG_PATH")
            if env_path and Path(env_path).exists():
                return Path(env_path)

            if path:
                explicit = Path(path)
                if explicit.exists():
                    return explicit
                raise ConfigError(f"指定的配置文件不存在: {explicit}")

            cwd_path = Path.cwd() / "config.yml"
            if cwd_path.exists():
                return cwd_path

            here = Path(__file__).resolve()
            for parent in here.parents:
                candidate = parent / "config.yml"
                if (parent / "pyproject.toml").exists() and candidate.exists():
                    return candidate
        except ConfigError:
            raise
        except PermissionError as e:
            logger.error(f"权限不足，无法访问文件路径，请检查宿主机权限或 Docker 挂载设置: {e}")
            raise ConfigError(f"无法访问配置路径: {e}") from e
        except Exception as e:
            logger.error(f"解析配置路径时发生未知错误: {e}")
            raise ConfigError(f"解析配置路径失败: {e}") from e

        raise ConfigError(
            "无法找到配置文件，请在工作目录创建 config.yml，或通过 -c/--config 显式指定路径"
        )

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding = "utf-8") as f:
                yaml.safe_dump(self.raw_config, f, allow_unicode = True, sort_keys = False)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise ConfigError(f"保存配置文件失败: {e}") from e

    def get_telegram_bot_token(self) -> str:
        token = self.raw_config.get("telegram_bot_token")
        if not token:
            logger.error("请在配置文件中设定 telegram_bot_token")
            raise ConfigError("请在配置文件中设定 telegram_bot_token")
        return str(token)

    def get_telegram_user_id(self) -> int:
        user_id = self.raw_config.get("telegram_user_id")
        if not user_id:
            logger.error("请在配置文件中设定 telegram_user_id")
            raise ConfigError("请在配置文件中设定 telegram_user_id")
        return parse_int(user_id)

    def get_tmdb_token(self) -> str:
        token = self.raw_config.get("tmdb_token")
        if not token:
            logger.error("请在配置文件中设定 tmdb_token")
            raise ConfigError("请在配置文件中设定 tmdb_token")
        return str(token)

    def get_downloader_config(self) -> Aria2Config:
        downloader_data = self.raw_config.get("downloader", {})
        aria2_data = downloader_data.get("aria2", None)
        if not aria2_data:
            logger.error("配置文件中缺少 'aria2' 节点")
            raise ConfigError("配置文件中缺少 downloader.aria2")

        try:
            return Aria2Config(**aria2_data)
        except Exception as e:
            logger.error(f"解析 'aria2' 配置失败，缺少必要字段: {e}")
            raise ConfigError(f"解析 aria2 配置失败: {e}") from e

    def get_storage_config(self) -> LocalStorageConfig | OpenlistStorageConfig | SftpStorageConfig:
        storage_data = self.raw_config.get("storage", {})
        provider = storage_data.get("provider", None)
        if not provider:
            logger.error("未指定 Provider，请在 storage 下配置 provider 字段")
            raise ConfigError("未指定 storage.provider")

        config_data = dict(storage_data.get(provider, {}) or {})
        if not config_data:
            logger.error(f"请检查 storage 节点下是否缺少 '{provider}' 的具体配置")
            raise ConfigError(f"缺少 storage.{provider} 配置")

        config_data["provider"] = provider
        config_data["folder_name_pattern"] = storage_data.get(
            "folder_name_pattern", "<filename> (<first_air_date.year>)/Season <season>"
        )
        config_data["video_name_pattern"] = storage_data.get(
            "video_name_pattern", "<filename> S<season:02d>E<episode:02d>.<ext>"
        )

        try:
            if provider == "local":
                return LocalStorageConfig(**config_data)
            elif provider == "openlist":
                return OpenlistStorageConfig(**config_data)
            elif provider == "sftp":
                return SftpStorageConfig(**config_data)
            else:
                logger.error(f"未知 Provider: {provider}")
                raise ConfigError(f"未知 storage.provider: {provider}")
        except ConfigError:
            raise
        except Exception as e:
            logger.error(f"解析 '{provider}' 存储配置失败，请检查字段名是否正确或有遗漏: {e}")
            raise ConfigError(f"解析 {provider} 存储配置失败: {e}") from e

    def get_anime_configs(self) -> list[BangumiConfig]:
        anime_list = self.raw_config.get("anime") or []

        if not isinstance(anime_list, list):
            logger.error("配置文件中 'anime' 节点格式不正确，应该是一个列表（使用 '-' 开头）")
            raise ConfigError("anime 节点必须是列表")

        configs = []
        for item in anime_list:
            try:
                configs.append(BangumiConfig(**item))
            except Exception as e:
                match_name = item.get("search_keyword") or item.get("filename") or "未知番剧"
                logger.error(f"解析番剧 [{match_name}] 配置失败，请检查是否漏填或错填了字段: {e}")
                raise ConfigError(f"解析番剧 [{match_name}] 失败: {e}") from e

        return configs

    def get_schedule(self) -> dict[str, Any]:
        data = self.raw_config.get("schedule") or {}
        if not isinstance(data, dict):
            raise ConfigError("schedule 节点必须是映射")
        try:
            return friendly_schedule(data)
        except ScheduleError:
            return friendly_schedule({"enabled": bool(data.get("enabled", False))})

    def set_schedule(self, spec: dict[str, Any]) -> None:
        normalized = friendly_schedule(spec)
        self.raw_config["schedule"] = {
            "enabled": normalized["enabled"],
            "mode": normalized["mode"],
            "hour": normalized["hour"],
            "minute": normalized["minute"],
            "interval_hours": normalized["interval_hours"],
            "weekday": normalized["weekday"],
            "cron": normalized["cron"],
        }
        self._save_config()

    def get_web_settings(self) -> dict[str, Any]:
        data = self.raw_config.get("web") or {}
        if not isinstance(data, dict):
            raise ConfigError("web 节点必须是映射")
        port = data.get("port", DEFAULT_WEB_PORT)
        return {
            "host": data.get("host") or DEFAULT_WEB_HOST,
            "port": parse_int(port, DEFAULT_WEB_PORT),
            "token": data.get("token") or "",
        }

    def add_anime_config(self, anime_dict: dict[str, Any]) -> bool:
        """
        向配置中动态添加番剧订阅
        :param anime_dict: 包含 BangumiConfig 所需键值对的字典
        :return: 是否添加成功
        """
        BangumiConfig(**anime_dict)
        anime_list = self.raw_config.get("anime") or []
        for existing in anime_list:
            if existing.get("filename") == anime_dict.get("filename") and parse_int(
                    existing.get("season"), 1
            ) == parse_int(anime_dict.get("season"), 1):
                logger.warning(
                    f"订阅已存在: {anime_dict.get('filename')} S{anime_dict.get('season')}"
                )
                return False

        anime_list.append(_plain(anime_dict))
        self.raw_config["anime"] = anime_list
        self._save_config()
        return True

    def remove_anime_config(self, filename: str, season: int) -> bool:
        anime_list = self.raw_config.get("anime") or []
        original_len = len(anime_list)

        self.raw_config["anime"] = [
            a
            for a in anime_list
            if not (a.get("filename") == filename and parse_int(a.get("season"), 1) == season)
        ]

        if len(self.raw_config["anime"]) < original_len:
            self._save_config()
            return True

        return False

    def public_view(self) -> dict[str, Any]:
        raw = _plain(deepcopy(self.raw_config))
        storage = raw.get("storage") or {}
        aria2 = (raw.get("downloader") or {}).get("aria2") or {}
        sftp = storage.get("sftp") or {}
        openlist = storage.get("openlist") or {}
        web = raw.get("web") or {}
        schedule = self.get_schedule()
        return {
            "config_path": str(self.config_path),
            "telegram_bot_token_set": bool(raw.get("telegram_bot_token")),
            "telegram_user_id": raw.get("telegram_user_id") or "",
            "tmdb_token_set": bool(raw.get("tmdb_token")),
            "downloader": {
                "aria2": {
                    "base_url": aria2.get("base_url") or "",
                    "token_set": bool(aria2.get("token")),
                }
            },
            "storage": {
                "provider": storage.get("provider") or "local",
                "folder_name_pattern": storage.get("folder_name_pattern")
                                       or "<filename> (<first_air_date.year>)/Season <season>",
                "video_name_pattern": storage.get("video_name_pattern")
                                      or "<filename> S<season:02d>E<episode:02d>.<ext>",
                "local": storage.get("local") or {"aria2_path": "", "target_path": ""},
                "sftp": {
                    "host": sftp.get("host") or "",
                    "port": sftp.get("port") or 22,
                    "user": sftp.get("user") or "",
                    "password_set": bool(sftp.get("password")),
                    "pub_key": sftp.get("pub_key") or "",
                    "aria2_path": sftp.get("aria2_path") or "",
                    "target_path": sftp.get("target_path") or "",
                },
                "openlist": {
                    "base_url": openlist.get("base_url") or "",
                    "user": openlist.get("user") or "",
                    "password_set": bool(openlist.get("password")),
                    "aria2_path": openlist.get("aria2_path") or "",
                    "target_path": openlist.get("target_path") or "",
                },
            },
            "web": {
                "host": web.get("host") or DEFAULT_WEB_HOST,
                "port": parse_int(web.get("port"), DEFAULT_WEB_PORT),
                "token_set": bool(web.get("token")),
            },
            "schedule": schedule,
            "anime": raw.get("anime") or [],
        }

    def apply_settings(self, payload: dict[str, Any]):
        """合并界面提交的配置。密钥字段空字符串表示保留原值。"""
        raw = self.raw_config
        _assign_secret(raw, "telegram_bot_token", payload.get("telegram_bot_token"))
        if payload.get("telegram_user_id") not in (None, ""):
            raw["telegram_user_id"] = parse_int(payload["telegram_user_id"])
        _assign_secret(raw, "tmdb_token", payload.get("tmdb_token"))

        downloader = payload.get("downloader") or {}
        aria2 = downloader.get("aria2") or {}
        if aria2:
            node = raw.setdefault("downloader", {}).setdefault("aria2", {})
            if aria2.get("base_url"):
                node["base_url"] = aria2["base_url"]
            _assign_secret(node, "token", aria2.get("token"))

        storage_payload = payload.get("storage") or {}
        if storage_payload:
            storage = raw.setdefault("storage", {})
            for key in ("provider", "folder_name_pattern", "video_name_pattern"):
                if storage_payload.get(key):
                    storage[key] = storage_payload[key]
            for provider in ("local", "sftp", "openlist"):
                incoming = storage_payload.get(provider)
                if not isinstance(incoming, dict):
                    continue
                node = storage.setdefault(provider, {})
                for key, value in incoming.items():
                    if key in ("password", "token"):
                        _assign_secret(node, key, value)
                    elif value not in (None, ""):
                        node[key] = parse_int(value) if key == "port" else value

        web_payload = payload.get("web") or {}
        if web_payload:
            web = raw.setdefault("web", {})
            if web_payload.get("host"):
                web["host"] = web_payload["host"]
            if web_payload.get("port") not in (None, ""):
                web["port"] = parse_int(web_payload["port"])
            _assign_secret(web, "token", web_payload.get("token"))

        self._save_config()


def _assign_secret(node: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text == "" or set(text) <= {"•", "*"}:
        return
    node[key] = text


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return (
            value.date().isoformat()
            if value.hour == value.minute == value.second == 0
            else value.isoformat()
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
