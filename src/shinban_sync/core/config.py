import os
from pathlib import Path
from typing import List

import yaml

from src.shinban_sync.core.logger import logger
from src.shinban_sync.models.config import Aria2Config, BangumiConfig
from src.shinban_sync.models.config import LocalStorageConfig, OpenlistStorageConfig, SftpStorageConfig


class ConfigManager:
    def __init__(self, config_path: str = None):
        self.config_path = self._resolve_config_path(config_path)

        try:
            with open(self.config_path, 'r', encoding = 'utf-8') as f:
                self.raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件 YAML 格式错误，请检查缩进或语法:\n{e}")
            exit(1)
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            exit(1)

    @staticmethod
    def _resolve_config_path(path: str = None) -> Path:
        try:
            # 环境变量指定的路径
            env_path = os.getenv("BANGUMI_CONFIG_PATH")
            if env_path and Path(env_path).exists():
                return Path(env_path)

            # 显式指定的路径
            if path and Path(path).exists():
                return Path(path)

            # 默认项目根目录
            project_root_path = Path(__file__).resolve().parent.parent.parent.parent / "config.yml"
            if project_root_path.exists():
                return project_root_path
        except PermissionError as e:
            logger.error(f"权限不足，无法访问文件路径，请检查宿主机权限或 Docker 挂载设置: {e}")
            exit(1)
        except Exception as e:
            logger.error(f"解析配置路径时发生未知错误: {e}")
            exit(1)

        logger.error("无法找到配置文件，请在项目根目录创建 config.yml 或通过启动参数 -c, --config 显式指定路径")
        exit(1)

    def _save_config(self):
        try:
            with open(self.config_path, 'w', encoding = 'utf-8') as f:
                yaml.dump(self.raw_config, f, allow_unicode = True, sort_keys = False)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")

    def get_telegram_bot_token(self) -> str:
        token = self.raw_config.get('telegram_bot_token')
        if not token:
            logger.error("请在配置文件中设定 telegram_bot_token")
            exit(1)

        return token

    def get_telegram_user_id(self) -> int:
        user_id = self.raw_config.get('telegram_user_id')
        if not user_id:
            logger.error("请在配置文件中设定 telegram_user_id")

        return user_id

    def get_tmdb_token(self) -> str | None:
        token = self.raw_config.get('tmdb_token')
        if not token:
            logger.error("请在配置文件中设定 tmdb_token")
            exit(1)

        return token

    def get_downloader_config(self) -> Aria2Config:
        downloader_data = self.raw_config.get('downloader', {})
        aria2_data = downloader_data.get('aria2', None)
        if not aria2_data:
            logger.error("配置文件中缺少 'aria2' 节点")
            exit(1)

        try:
            return Aria2Config(**aria2_data)
        except Exception as e:
            logger.error(f"解析 'aria2' 配置失败，缺少必要字段: {e}")
            exit(1)

    def get_storage_config(self) -> LocalStorageConfig | OpenlistStorageConfig | SftpStorageConfig:
        storage_data = self.raw_config.get('storage', {})
        provider = storage_data.get('provider', None)
        if not provider:
            logger.error("未指定 Provider，请在 storage 下配置 provider 字段")
            exit(1)

        config_data = storage_data.get(provider, {})
        if not config_data:
            logger.error(f"请检查 storage 节点下是否缺少 '{provider}' 的具体配置")
            exit(1)

        config_data['provider'] = provider
        config_data['folder_name_pattern'] = storage_data.get(
            'folder_name_pattern', '<filename> (<first_air_date.year>)/Season <season>'
        )
        config_data['video_name_pattern'] = storage_data.get(
            'video_name_pattern', '<filename> S<season:02d>E<episode:02d>.<ext>'
        )

        try:
            if provider == 'local':
                return LocalStorageConfig(**config_data)
            elif provider == 'openlist':
                return OpenlistStorageConfig(**config_data)
            elif provider == 'sftp':
                return SftpStorageConfig(**config_data)
            else:
                logger.error(f"未知 Provider: {provider}")
                exit(1)
        except Exception as e:
            logger.error(f"解析 '{provider}' 存储配置失败，请检查字段名是否正确或有遗漏: {e}")
            exit(1)

    def get_anime_configs(self) -> List[BangumiConfig]:
        anime_list = self.raw_config.get('anime') or []

        if not isinstance(anime_list, list):
            logger.error("配置文件中 'anime' 节点格式不正确，应该是一个列表（使用 '-' 开头）")
            exit(1)

        configs = []
        for item in anime_list:
            try:
                configs.append(BangumiConfig(**item))
            except Exception as e:
                match_name = item.get('match_name', '未知番剧')
                logger.error(f"解析番剧 [{match_name}] 配置失败，请检查是否漏填或错填了字段: {e}")
                exit(1)

        return configs

    def add_anime_config(self, anime_dict: dict) -> bool:
        """
        向配置中动态添加番剧订阅
        :param anime_dict: 包含 BangumiConfig 所需键值对的字典
        :return: 是否添加成功
        """
        anime_list = self.raw_config.get('anime') or []
        for existing in anime_list:
            if (existing.get('filename') == anime_dict.get('filename') and
                    existing.get('season') == anime_dict.get('season')):
                logger.warning(f"订阅已存在: {anime_dict.get('filename')} S{anime_dict.get('season')}")
                return False

        anime_list.append(anime_dict)
        self.raw_config['anime'] = anime_list
        self._save_config()
        return True

    def remove_anime_config(self, filename: str, season: int) -> bool:
        anime_list = self.raw_config.get('anime') or []
        original_len = len(anime_list)

        self.raw_config['anime'] = [
            a for a in anime_list
            if not (a.get('filename') == filename and a.get('season') == season)
        ]

        if len(self.raw_config['anime']) < original_len:
            self._save_config()
            return True

        return False
