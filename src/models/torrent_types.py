from aioqbt.api import TorrentInfo as TorrentInfoAioqbt
from aioqbt.api import TorrentProperties


class TorrentInfo(TorrentProperties, TorrentInfoAioqbt):
    pass
