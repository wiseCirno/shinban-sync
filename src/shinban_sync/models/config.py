from dataclasses import dataclass
from datetime import datetime

from shinban_sync.models.bangumi import SubtitleGroup


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
    first_air_date: datetime | None = None
    season: int = 1
    episode_count: int = 12
    language: str = "chs"
    title: str = ""

    def __post_init__(self):
        def _ensure_dt(val: object, required: bool) -> datetime | None:
            if val is None:
                if required:
                    raise TypeError("日期不能为空")
                return None
            if isinstance(val, datetime):
                return val if val.tzinfo is not None else val.astimezone()
            if isinstance(val, str):
                dt = datetime.fromisoformat(val)
                return dt if dt.tzinfo is not None else dt.astimezone()
            raise TypeError(f"无法解析日期: {val!r}")

        def _ensure_subtitle(val: object) -> SubtitleGroup:
            if isinstance(val, SubtitleGroup):
                return val
            if isinstance(val, str):
                try:
                    return SubtitleGroup[val]
                except KeyError:
                    raise KeyError(f"Invalid provider: {val}") from None
            raise TypeError(f"无法解析字幕组: {val!r}")

        self.first_air_date = _ensure_dt(self.first_air_date, required = False)
        season_air_date = _ensure_dt(self.season_air_date, required = True)
        if season_air_date is None:
            raise TypeError("season_air_date 不能为空")
        self.season_air_date = season_air_date
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
    password: str | None
    pub_key: str | None
