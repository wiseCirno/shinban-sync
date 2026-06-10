from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.shinban_sync.models.bangumi import SubtitleGroup


@dataclass
class Aria2Config:
    base_url: str
    token: str


@dataclass
class BangumiConfig:
    search_keyword: str
    filename: str
    subtitle: SubtitleGroup
    season_air_date: datetime
    first_air_date: Optional[datetime] = None
    season: int = 1
    episode_count: int = 12
    language: str = 'chs'

    def __post_init__(self):
        def _ensure_dt(val):
            if isinstance(val, str):
                dt = datetime.fromisoformat(val)
                return dt if dt.tzinfo is not None else dt.astimezone()
            return val

        def _ensure_subtitle(val):
            if isinstance(val, str):
                try:
                    return SubtitleGroup[val]
                except KeyError:
                    raise KeyError(f"Invalid provider: {val}")
            return val

        self.first_air_date = _ensure_dt(self.first_air_date)
        self.season_air_date = _ensure_dt(self.season_air_date)
        self.subtitle = _ensure_subtitle(self.subtitle)

        if self.season == 1 and not self.first_air_date:
            self.first_air_date = self.season_air_date
        elif not self.first_air_date:
            raise ValueError("first_air_date is required when season is not 1")


@dataclass
class BaseStorageConfig:
    provider: str
    aria2_path: str
    target_path: str
    folder_name_pattern: str
    video_name_pattern: str


@dataclass
class LocalStorageConfig(BaseStorageConfig):
    pass


@dataclass
class OpenlistStorageConfig(BaseStorageConfig):
    base_url: str
    user: str
    password: str


@dataclass
class SftpStorageConfig(BaseStorageConfig):
    host: str
    port: int
    user: str
    password: Optional[str]
    pub_key: Optional[str]
