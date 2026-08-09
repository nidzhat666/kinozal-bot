from time import perf_counter

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import QBT_CREDENTIALS
from bot.constants import MAGNET_ADD_CALLBACK
from services.qbt_services import add_magnet, get_client, qbt_get_categories
from utilities.handlers_utils import check_action, redis_callback_get, redis_callback_save
from utilities.logger_utils import get_handler_logger

router = Router(name=__name__)
logger = get_handler_logger("magnet_link")


def _is_magnet_link(text: str | None) -> bool:
    return (text or "").strip().lower().startswith("magnet:?")


@router.message(lambda m: _is_magnet_link(m.text))
async def handle_magnet_link(message: Message):
    """Ask for a qBittorrent category when a magnet link is pasted into the chat."""
    magnet_link = message.text.strip()
    user_id = message.from_user.id if message.from_user else None
    handler_logger = logger.bind(user_id=user_id)
    handler_logger.info("Magnet link received")

    qbt_client = await get_client(**QBT_CREDENTIALS)
    async with qbt_client:
        categories = await qbt_get_categories(qbt_client)

    if not categories:
        await message.answer("Не удалось получить список категорий qBittorrent.")
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=category,
                callback_data=redis_callback_save(
                    {
                        "action": MAGNET_ADD_CALLBACK,
                        "magnet": magnet_link,
                        "category": category,
                    }
                ),
            )
        ]
        for category in categories
    ]
    await message.answer(
        "Это фильм или сериал? Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(lambda c: check_action(c.data, MAGNET_ADD_CALLBACK))
async def handle_magnet_add(callback_query: CallbackQuery):
    """Add the magnet link to qBittorrent under the selected category."""
    started_at = perf_counter()
    user_id = callback_query.from_user.id if callback_query.from_user else None
    handler_logger = logger.bind(user_id=user_id)

    callback_data = redis_callback_get(callback_query.data)
    magnet_link = callback_data.get("magnet") if callback_data else None
    category = callback_data.get("category") if callback_data else None

    if not magnet_link or not category:
        await callback_query.answer(
            "Не удалось найти магнет-ссылку. Отправьте её заново.", show_alert=True
        )
        return

    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            await add_magnet(magnet_link, qbt_client, category)

        await callback_query.message.edit_text(f"Магнет-ссылка добавлена в категорию «{category}».")
        duration_ms = int((perf_counter() - started_at) * 1000)
        handler_logger.info(
            "Magnet link added to qBittorrent", category=category, duration_ms=duration_ms
        )
        await callback_query.answer()
    except Exception as e:
        duration_ms = int((perf_counter() - started_at) * 1000)
        handler_logger.error(
            "Error adding magnet link",
            error_type=type(e).__name__,
            error_message=str(e),
            duration_ms=duration_ms,
            exc_info=True,
        )
        await callback_query.answer(f"Не удалось добавить: {e}", show_alert=True)
