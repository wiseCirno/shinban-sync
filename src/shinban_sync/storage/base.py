import os.path
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.config import BangumiConfig, BaseStorageConfig
from shinban_sync.utils.numbers import parse_float, parse_int


class BaseProvider(ABC):
    def __init__(self, storage: BaseStorageConfig) -> None:
        self.storage: BaseStorageConfig = storage

    def __enter__(self) -> Self:
        return self

    def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        return None

    @abstractmethod
    def rename_and_move_bangumi(
            self, info: BangumiInfo, config: BangumiConfig, file_name: str
    ) -> str:
        pass

    @abstractmethod
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        pass

    @staticmethod
    def _render_pattern(
            pattern: str,
            config: BangumiConfig,
            info: BangumiInfo | None = None,
            ext: str = "",
    ) -> str:
        """
        将 <var> 替换为 {var} 并调用原生 format()
        """
        fmt_string = pattern.replace("<", "{").replace(">", "}")
        kwargs = {
            "filename": config.filename,
            "subtitle": config.subtitle,
            "first_air_date": config.first_air_date,
            "season_air_date": config.season_air_date,
            "season": config.season,
            "episode": parse_int(parse_float(info.episode), 0) if info else 0,
            "language": config.language,
            "ext": ext.replace(".", ""),
        }

        return fmt_string.format(**kwargs)

    def get_standardized_filename(
            self, info: BangumiInfo, config: BangumiConfig, file_name: str
    ) -> str:
        ext = os.path.splitext(file_name)[1]
        if ext.lower() not in [".mp4", ".mkv", ".ass"]:
            return ""

        return self._render_pattern(self.storage.video_name_pattern, config, info, ext)

    def get_target_dir(self, config: BangumiConfig) -> str:
        rendered_folder = self._render_pattern(self.storage.folder_name_pattern, config)
        return f"{self.storage.target_path}/{rendered_folder}".replace("//", "/")
