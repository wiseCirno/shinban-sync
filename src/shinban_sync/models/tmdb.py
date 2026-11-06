from typing import Any

from pydantic import BaseModel


class TMDBGenre(BaseModel):
    id: int
    name: str


class TMDBEpisode(BaseModel):
    id: int
    name: str
    overview: str
    vote_average: float
    vote_count: int
    air_date: str
    episode_number: int
    episode_type: str
    production_code: str
    season_number: int
    show_id: int
    runtime: int | None = None
    still_path: str | None = None


class TMDBCompany(BaseModel):
    id: int
    name: str
    origin_country: str
    logo_path: str | None = None


class TMDBCountry(BaseModel):
    iso_3166_1: str
    name: str


class TMDBSeason(BaseModel):
    id: int
    name: str
    overview: str
    episode_count: int
    season_number: int
    vote_average: float
    air_date: str | None = None
    poster_path: str | None = None


class TMDBSpokenLanguage(BaseModel):
    english_name: str
    iso_639_1: str
    name: str


class TMDBSeriesDetails(BaseModel):
    id: int
    name: str
    original_name: str
    original_language: str
    overview: str
    tagline: str
    status: str
    type: str
    homepage: str
    first_air_date: str
    last_air_date: str
    in_production: bool
    popularity: float
    vote_average: float
    vote_count: int
    adult: bool
    number_of_episodes: int
    number_of_seasons: int
    episode_run_time: list[int]
    languages: list[str]
    origin_country: list[str]
    backdrop_path: str | None = None
    poster_path: str | None = None

    genres: list[TMDBGenre] = []
    networks: list[TMDBCompany] = []
    production_companies: list[TMDBCompany] = []
    production_countries: list[TMDBCountry] = []
    seasons: list[TMDBSeason] = []
    spoken_languages: list[TMDBSpokenLanguage] = []
    created_by: list[object] = []

    last_episode_to_air: TMDBEpisode | None = None
    next_episode_to_air: TMDBEpisode | None = None

    @classmethod
    def from_json(cls, raw_data: str | dict[str, Any]):
        return (
            cls.model_validate(raw_data)
            if isinstance(raw_data, dict)
            else cls.model_validate_json(raw_data)
        )


class TMDBAlternativeTitleItem(BaseModel):
    iso_3166_1: str
    title: str
    type: str = ""


class TMDBAlternativeTitles(BaseModel):
    id: int
    results: list[TMDBAlternativeTitleItem] = []

    @classmethod
    def from_json(cls, raw_data: str | dict[str, Any]):
        return (
            cls.model_validate(raw_data)
            if isinstance(raw_data, dict)
            else cls.model_validate_json(raw_data)
        )

    def get_titles_by_country(self, country_codes: list[str]) -> list[str]:
        return [
            item.title
            for item in self.results
            if item.iso_3166_1.upper() in [code.upper() for code in country_codes]
        ]


class TMDBTVSearchItem(BaseModel):
    id: int
    name: str
    original_name: str
    original_language: str
    overview: str
    popularity: float
    vote_average: float
    vote_count: int
    adult: bool = False

    genre_ids: list[int] = []
    origin_country: list[str] = []

    backdrop_path: str | None = None
    poster_path: str | None = None
    first_air_date: str | None = ""


class TMDBTVSearchResult(BaseModel):
    page: int
    results: list[TMDBTVSearchItem] = []
    total_pages: int
    total_results: int

    @classmethod
    def from_json(cls, raw_data: str | dict[str, Any]):
        return (
            cls.model_validate(raw_data)
            if isinstance(raw_data, dict)
            else cls.model_validate_json(raw_data)
        )

    def get_best_match(self) -> TMDBTVSearchItem | None:
        return self.results[0] if self.results else None
