from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.constants import REFRESH_PLEX_COMMAND
from services.plex_services.scan_library_service import refresh_plex_library

router = Router(name=__name__)


@router.message(Command(REFRESH_PLEX_COMMAND))
async def handle_refresh_plex_command(message: Message):
    result = await refresh_plex_library()
    await message.answer(result)
