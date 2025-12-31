from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VideoQuality(StrEnum):
    # 4K variants (highest quality first)
    UHD_4K_REMUX = "4K REMUX"
    UHD_4K_HDR_DV = "4K HDR DV"
    UHD_4K_HDR = "4K HDR"
    UHD_4K_BDRIP = "4K BDRip"
    UHD_4K = "4K"
    
    # 1080p variants
    FHD_1080P_REMUX = "1080p REMUX"
    FHD_1080P_BLURAY = "1080p BluRay"
    FHD_1080P_WEB = "1080p WEB-DL"
    FHD_1080P_BDRIP = "1080p BDRip"
    FHD_1080P = "1080p"
    HD_1080I = "1080i"
    
    # 720p variants
    HD_720P_BLURAY = "720p BluRay"
    HD_720P_WEB = "720p WEB-DL"
    HD_720P_BDRIP = "720p BDRip"
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
    def priority(self) -> int:
        """Return priority for sorting (lower number = better quality).
        
        Priority is based on emoji rating:
        🥇 (Gold) = 0 (best)
        🥈 (Silver) = 1
        🥉 (Bronze) = 2
        ⚠️ (Caution) = 3
        ❌ (Avoid) = 4 (worst)
        """
        emoji = self.rating_emoji
        if emoji == "🥇":
            return 0
        elif emoji == "🥈":
            return 1
        elif emoji == "🥉":
            return 2
        elif emoji == "⚠️":
            return 3
        elif emoji == "❌":
            return 4
        else:
            # Unknown/❓ - treat as worst
            return 999

    @property
    def rating_emoji(self) -> str:
        """Return quality rating emoji based on preference ranking.
        
        🥇 - Gold: WEB-DL 1080p (best choice)
        🥈 - Silver: BDRip 1080p, BluRay 1080p (great quality)
        🥉 - Bronze: 4K WEB-DL/BDRip (optional, bigger size)
        ⚠️ - Caution: REMUX (enthusiast only, huge size)
        ❌ - Avoid: HDRip, WEBRip, DVDRip, 720p, SD (outdated/bad quality)
        """
        match self:
            # 🥇 Gold - WEB-DL 1080p
            case VideoQuality.FHD_1080P_WEB:
                return "🥇"

            # 🥈 Silver - BDRip 1080p
            case VideoQuality.FHD_1080P_BDRIP:
                return "🥈"

            # 🥉 Bronze - 4K variants (except REMUX)
            case (
            VideoQuality.UHD_4K
            | VideoQuality.UHD_4K_HDR
            | VideoQuality.UHD_4K_BDRIP
            ):
                return "🥉"

            # ⚠️ Caution - REMUX (huge files)
            case (VideoQuality.UHD_4K_REMUX
                  | VideoQuality.FHD_1080P_REMUX
                  | VideoQuality.FHD_1080P_BLURAY
                  | VideoQuality.UHD_4K_HDR_DV):
                return "⚠️"

            # ❌ Avoid - HDRip, WEBRip, DVDRip, 720p, SD, generic
            case (
            VideoQuality.HDRIP
            | VideoQuality.WEBRIP
            | VideoQuality.DVDRIP
            | VideoQuality.HD_720P
            | VideoQuality.HD_720P_BLURAY
            | VideoQuality.HD_720P_WEB
            | VideoQuality.HD_720P_BDRIP
            | VideoQuality.SD_576P
            | VideoQuality.SD_480P
            | VideoQuality.HD_1080I
            | VideoQuality.FHD_1080P
            | VideoQuality.BDRIP
            ):
                return "❌"

        return "❓"

    @property
    def match_rules(self) -> list[tuple[list[str], list[str]]]:
        """Returns list of (required_all, required_any) tuples.
        
        A rule matches if ALL keywords from required_all are present
        AND AT LEAST ONE keyword from required_any is present.
        If required_any is empty, only required_all is checked.
        """
        match self:
            # 4K variants
            case VideoQuality.UHD_4K_REMUX:
                return [
                    (["remux"], ["2160p", "4k", "uhd"]),
                ]
            case VideoQuality.UHD_4K_HDR_DV:
                return [
                    (["dolby vision"], []),
                    (["dovi"], []),
                    (["dv"], ["hdr"]),
                ]
            case VideoQuality.UHD_4K_HDR:
                return [
                    (["hdr"], ["2160p", "4k", "uhd"]),
                    (["hdr10"], []),
                    (["hdr10+"], []),
                ]
            case VideoQuality.UHD_4K_BDRIP:
                return [
                    (["bdrip"], ["2160p", "4k", "uhd"]),
                    (["bd-rip"], ["2160p", "4k", "uhd"]),
                ]
            case VideoQuality.UHD_4K:
                return [
                    (["2160p"], []),
                    (["4k"], []),
                    (["uhd"], []),
                ]
            
            # 1080p variants
            case VideoQuality.FHD_1080P_REMUX:
                return [
                    (["remux", "1080"], []),
                    (["remux"], ["1080p", "fhd"]),
                ]
            case VideoQuality.FHD_1080P_BLURAY:
                return [
                    (["1080p"], ["bluray", "blu-ray"]),
                ]
            case VideoQuality.FHD_1080P_WEB:
                return [
                    (["1080p"], ["web-dl", "webdl"]),
                    (["web-dl", "webdl"], ["1080p", "fhd"]),
                ]
            case VideoQuality.FHD_1080P_BDRIP:
                return [
                    (["1080p"], ["bdrip", "bd-rip"]),
                ]
            case VideoQuality.FHD_1080P:
                return [
                    (["1080p"], []),
                    (["fhd"], []),
                ]
            case VideoQuality.HD_1080I:
                return [
                    (["1080i"], []),
                ]
            
            # 720p variants
            case VideoQuality.HD_720P_BLURAY:
                return [
                    (["720p"], ["bluray", "blu-ray"]),
                ]
            case VideoQuality.HD_720P_WEB:
                return [
                    (["720p"], ["web-dl", "webdl"]),
                    (["web-dl", "webdl"], ["720p"]),
                ]
            case VideoQuality.HD_720P_BDRIP:
                return [
                    (["720p"], ["bdrip", "bd-rip"]),
                ]
            case VideoQuality.HD_720P:
                return [
                    (["720p"], []),
                ]
            
            # SD variants
            case VideoQuality.SD_576P:
                return [
                    (["576p"], []),
                    (["576i"], []),
                ]
            case VideoQuality.SD_480P:
                return [
                    (["480p"], []),
                    (["480i"], []),
                ]
            
            # Source-based fallbacks
            case VideoQuality.BDRIP:
                return [
                    (["bdrip"], []),
                    (["bd-rip"], []),
                ]
            case VideoQuality.HDRIP:
                return [
                    (["hdrip"], []),
                    (["hd-rip"], []),
                ]
            case VideoQuality.DVDRIP:
                return [
                    (["dvdrip"], []),
                    (["dvd-rip"], []),
                ]
            case VideoQuality.WEBRIP:
                return [
                    # Check for WEBRip with resolution (more specific)
                    (["webrip"], ["1080p", "720p", "2160p", "4k"]),
                    (["web-rip"], ["1080p", "720p", "2160p", "4k"]),
                    # Fallback to WEBRip without resolution
                    (["webrip"], []),
                    (["web-rip"], []),
                    (["web-dlrip"], []),
                    (["webdlrip"], []),
                ]
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
    torrent_html_content: str | None = None


class MovieSearchResult(MovieDetails):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="movie_id")
    size: str
    search_name: str | None = None
    seeds: int | None = None
    peers: int | None = None
    has_full_details: bool = False
    provider_name: str | None = None

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
        provider_name: str | None = None,
    ) -> "MovieSearchResult":
        return cls(
            movie_id=str(search_id),
            size=size,
            search_name=search_name,
            seeds=seeds,
            peers=peers,
            has_full_details=has_full_details,
            provider_name=provider_name,
            **details.model_dump(),
        )
