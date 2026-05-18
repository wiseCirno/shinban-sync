import os.path
from abc import ABC, abstractmethod
from typing import Optional

from src.shinban_sync.models.bangumi import BangumiInfo
from src.shinban_sync.models.config import BangumiConfig, BaseStorageConfig


class BaseProvider(ABC):
    def __init__(self, storage: BaseStorageConfig) -> None:
        self.storage = storage

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    def rename_and_move_bangumi(self, info: BangumiInfo, config: BangumiConfig, file_name: str) -> None:
        pass

    @abstractmethod
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        pass

    @staticmethod
    def _render_pattern(pattern: str, config: BangumiConfig,
                        info: Optional[BangumiInfo] = None, ext: str = "") -> str:
        """
        将 <var> 替换为 {var} 并调用原生 format()
        """
        fmt_string = pattern.replace('<', '{').replace('>', '}')
        kwargs = {
            "filename": config.filename,
            "subtitle": config.subtitle,
            "first_air_date": config.first_air_date,
            "season_air_date": config.season_air_date,
            "season": config.season,
            "episode": int(float(info.episode)) if info else 0,
            "language": config.language,
            "ext": ext.replace(".", "")
        }

        return fmt_string.format(**kwargs)

    def get_standardized_filename(self, info: BangumiInfo, config: BangumiConfig, file_name: str) -> str:
        ext = os.path.splitext(file_name)[1]
        if ext.lower() not in [".mp4", ".mkv", ".ass"]:
            return ""

        return self._render_pattern(self.storage.video_name_pattern, config, info, ext)

    def get_target_dir(self, config: BangumiConfig) -> str:
        rendered_folder = self._render_pattern(self.storage.folder_name_pattern, config)
        return f"{self.storage.target_path}/{rendered_folder}".replace('//', '/')
