from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VideoQuality(StrEnum):
    # 4K variants (highest quality first)
    UHD_4K_REMUX = "4K REMUX"
    UHD_4K_HDR_DV = "4K HDR DV"
    UHD_4K_HDR = "4K HDR"
    UHD_4K = "4K"
    
    # 1080p variants
    FHD_1080P_REMUX = "1080p REMUX"
    FHD_1080P_BLURAY = "1080p BluRay"
    FHD_1080P_WEB = "1080p WEB-DL"
    FHD_1080P = "1080p"
    HD_1080I = "1080i"
    
    # 720p variants
    HD_720P_BLURAY = "720p BluRay"
    HD_720P_WEB = "720p WEB-DL"
    HD_720P = "720p"
    
    # SD variants
    SD_576P = "576p"
    SD_480P = "480p"
    
    # Source-based (when resolution unclear)
    BDRIP = "BDRip"
    HDRIP = "HDRip"
    DVDRIP = "DVDRip"
    WEBRIP = "WEBRip"

    @property
    def keywords(self) -> list[str]:
        match self:
            # 4K variants - check more specific first
            case VideoQuality.UHD_4K_REMUX:
                return ["2160p remux", "4k remux", "uhd remux"]
            case VideoQuality.UHD_4K_HDR_DV:
                return ["dolby vision", "dovi", "dv hdr"]
            case VideoQuality.UHD_4K_HDR:
                return ["2160p hdr", "4k hdr", "uhd hdr", "hdr10+", "hdr10"]
            case VideoQuality.UHD_4K:
                return ["2160p", "4k", "uhd"]
            
            # 1080p variants
            case VideoQuality.FHD_1080P_REMUX:
                return ["1080p remux", "remux 1080"]
            case VideoQuality.FHD_1080P_BLURAY:
                return ["1080p bluray", "1080p blu-ray"]
            case VideoQuality.FHD_1080P_WEB:
                return ["1080p web-dl", "1080p webdl", "1080p web"]
            case VideoQuality.FHD_1080P:
                return ["1080p", "fhd"]
            case VideoQuality.HD_1080I:
                return ["1080i"]
            
            # 720p variants
            case VideoQuality.HD_720P_BLURAY:
                return ["720p bluray", "720p blu-ray"]
            case VideoQuality.HD_720P_WEB:
                return ["720p web-dl", "720p webdl", "720p web"]
            case VideoQuality.HD_720P:
                return ["720p"]
            
            # SD variants
            case VideoQuality.SD_576P:
                return ["576p", "576i"]
            case VideoQuality.SD_480P:
                return ["480p", "480i"]
            
            # Source-based fallbacks
            case VideoQuality.BDRIP:
                return ["bdrip", "bd-rip"]
            case VideoQuality.HDRIP:
                return ["hdrip", "hd-rip"]
            case VideoQuality.DVDRIP:
                return ["dvdrip", "dvd-rip"]
            case VideoQuality.WEBRIP:
                return ["webrip", "web-rip"]
        return []


class MovieRatings(BaseModel):
    imdb: str = "-"
    kinopoisk: str = "-"


class TorrentDetails(BaseModel):
    key: str
    value: str | None = None


class AudioLanguage(BaseModel):
    language: str  # RUS, ENG, UKR, ...
    quality: str  # DUB, SUB, Original, ...


class MovieDetails(BaseModel):
    name: str
    year: str
    genres: list[str]
    director: str
    actors: list[str]
    season: int | None = None
    image_url: str | None = None
    video_quality: str | None = None
    audio_quality: str | None = None
    audio_language: list[AudioLanguage] | None = []
    ratings: MovieRatings
    torrent_details: list[TorrentDetails]


class MovieSearchResult(MovieDetails):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="movie_id")
    size: str
    search_name: str | None = None
    seeds: int | None = None
    peers: int | None = None
    has_full_details: bool = False

    @classmethod
    def from_search_data(
        cls,
        *,
        search_id: str,
        size: str,
        search_name: str,
        details: MovieDetails,
        seeds: int | None = None,
        peers: int | None = None,
        has_full_details: bool = False,
    ) -> "MovieSearchResult":
        return cls(
            movie_id=str(search_id),
            size=size,
            search_name=search_name,
            seeds=seeds,
            peers=peers,
            has_full_details=has_full_details,
            **details.model_dump(),
        )
