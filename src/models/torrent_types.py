from aioqbt.api import TorrentProperties
from aioqbt.api import TorrentInfo as TorrentInfoAioqbt


class TorrentInfo(TorrentProperties, TorrentInfoAioqbt):
    pass
