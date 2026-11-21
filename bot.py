"""Korea Zura Telegram shop bot. Configure via environment variables."""
import json
import logging
import os
from contextlib import ExitStack
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

logging.basicConfig(level=logging.INFO)
CATALOG_PATH = Path(__file__).with_name("catalog.json")
SIZE, CONTACT = range(2)


def catalog():
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👗 Каталог платьев", callback_data="catalog")],
        [InlineKeyboardButton("🧥 Верхняя одежда", callback_data="outerwear")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Добро пожаловать в Korea Zura! 🛍️ Выберите товар из каталога.",
        reply_markup=menu(),
    )


DRESS_SECTIONS = {
    "mayak": "Маячные модели",
    "monica": "Monica.Magni",
    "cupra": "Платья из купры",
    "cotton": "Платья из хлопка",
    "velour": "Велюровые халаты",
    "other": "Другие платья",
}
PAGE_SIZE = 6
MAYAK_PAGE_SIZE = 9


def dress_section(item):
    prefix = item["id"].split("-", 1)[0]
    if prefix != "other" and prefix in DRESS_SECTIONS:
        return prefix
    if "маячн" in item.get("description", "").casefold():
        return "mayak"
    return "other"


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dresses = []
    outerwear = []
    for item in catalog():
        (outerwear if item.get("category") == "outerwear" else dresses).append(item)

    if query.data == "menu":
        await query.edit_message_text("Выберите раздел каталога", reply_markup=menu())
        return

    if query.data == "catalog":
        available_sections = {dress_section(item) for item in dresses}
        buttons = [
            [InlineKeyboardButton(label, callback_data=f"browse:{section}:0")]
            for section, label in DRESS_SECTIONS.items()
            if section in available_sections
        ]
        buttons.append([InlineKeyboardButton("‹ Главное меню", callback_data="menu")])
        title = "Выберите раздел платьев" if dresses else "Каталог скоро пополнится! 💕"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(buttons))
        return

    section, page = "outerwear", 0
    if query.data.startswith("browse:"):
        _, section, page_text = query.data.split(":")
        page = int(page_text)
    if section == "outerwear":
        items, title, back = outerwear, "Верхняя одежда", "menu"
    else:
        items = [item for item in dresses if dress_section(item) == section]
        title, back = DRESS_SECTIONS[section], "catalog"

    page_size = MAYAK_PAGE_SIZE if section == "mayak" else PAGE_SIZE
    page_count = max(1, (len(items) + page_size - 1) // page_size)
    page = min(page, page_count - 1)
    start_index = page * page_size
    page_items = items[start_index:start_index + page_size]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("‹ Назад", callback_data=f"browse:{section}:{page - 1}"))
    if page + 1 < page_count:
        navigation.append(InlineKeyboardButton("Далее ›", callback_data=f"browse:{section}:{page + 1}"))
    back_button = [InlineKeyboardButton("‹ К разделам", callback_data=back)]
    if not page_items:
        await query.edit_message_text(
            "Каталог скоро пополнится! 💕",
            reply_markup=InlineKeyboardMarkup([back_button]),
        )
        return
    await show_album(query.message, title, page_items, page, page_count, navigation, back_button)


async def show_album(message, title, items, page, page_count, navigation, back_button):
    model_buttons = []
    with ExitStack() as files:
        photos = []
        for number, item in enumerate(items, 1):
            name = item["name"].split(" · ", 1)[-1]
            caption = f"{number}. {name}"
            photo = item.get("photo_url")
            if item.get("photo_path"):
                try:
                    photo = files.enter_context((CATALOG_PATH.parent / item["photo_path"]).open("rb"))
                except OSError:
                    logging.warning("Could not open photo for %s", item["id"])
            if photo:
                photos.append(InputMediaPhoto(photo, caption=caption))
            model_buttons.append(InlineKeyboardButton(str(number), callback_data=f'item:{item["id"]}'))

        if len(photos) > 1:
            try:
                await message.reply_media_group(photos)
            except BadRequest:
                logging.warning("Could not send catalog album, trying photos individually")
                for photo in photos:
                    try:
                        await message.reply_photo(photo.media, caption=photo.caption)
                    except BadRequest:
                        logging.warning("Could not send catalog photo: %s", photo.caption)
        elif photos:
            try:
                await message.reply_photo(photos[0].media, caption=photos[0].caption)
            except BadRequest:
                logging.warning("Could not send catalog photo: %s", photos[0].caption)

    buttons = [model_buttons[index:index + PAGE_SIZE] for index in range(0, len(model_buttons), PAGE_SIZE)]
    if navigation:
        buttons.append(navigation)
    buttons.append(back_button)
    await message.reply_text(
        f"{title} · {page + 1}/{page_count}\nНажмите номер модели, чтобы увидеть цену и размеры.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = query.data.split(":", 1)[1]
    item = next((x for x in catalog() if str(x["id"]) == item_id), None)
    if not item:
        await query.message.reply_text("Товар не найден.")
        return
    details = [item["name"]]
    for key, label in (("price", "Цена"), ("sizes", "Размеры"), ("colors", "Цвета"), ("description", "Описание")):
        value = item.get(key)
        if value:
            details.append(f'{label}: {", ".join(map(str, value)) if isinstance(value, list) else value}')
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Заказать", callback_data=f"order:{item_id}")]])
    photo_path = item.get("photo_path")
    photo = item.get("photo_url")
    if photo_path:
        with (CATALOG_PATH.parent / photo_path).open("rb") as photo_file:
            await query.message.reply_photo(photo=photo_file, caption="\n".join(details), reply_markup=buttons)
        extra_photo_path = item.get("extra_photo_path")
        if extra_photo_path:
            with (CATALOG_PATH.parent / extra_photo_path).open("rb") as extra_photo:
                await query.message.reply_photo(photo=extra_photo)
    elif photo:
        await query.message.reply_photo(photo=photo, caption="\n".join(details), reply_markup=buttons)
    else:
        await query.message.reply_text("\n".join(details), reply_markup=buttons)


async def begin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = query.data.split(":", 1)[1]
    item = next((x for x in catalog() if str(x["id"]) == item_id), None)
    if not item:
        await query.message.reply_text("Товар не найден.")
        return ConversationHandler.END
    context.user_data["order_item"] = item
    await query.message.reply_text("Напишите нужный размер (или /cancel для отмены):")
    return SIZE


async def save_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    size = update.message.text.strip()[:50]
    item = context.user_data["order_item"]
    allowed = [str(s).casefold() for s in item.get("sizes", [])]
    if allowed and size.casefold() not in allowed:
        await update.message.reply_text("Пожалуйста, выберите размер из карточки товара.")
        return SIZE
    context.user_data["order_size"] = size
    await update.message.reply_text("Напишите имя и телефон для связи (или /cancel):")
    return CONTACT


async def finish_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = os.environ.get("ADMIN_CHAT_ID")
    if not admin_id:
        await update.message.reply_text("Приём заказов пока не настроен. Попробуйте позже.")
        return ConversationHandler.END
    item = context.user_data["order_item"]
    contact = update.message.text.strip()[:300]
    user = update.effective_user
    message = (
        "🛍 Новый заказ Korea Zura\n"
        f'Товар: {item["name"]} (ID: {item["id"]})\n'
        f'Размер: {context.user_data["order_size"]}\n'
        f'Контакт: {contact}\n'
        f'Покупатель Telegram: @{user.username or "без username"} (ID: {user.id})'
    )
    try:
        await context.bot.send_message(chat_id=int(admin_id), text=message)
    except Exception:
        logging.exception("Could not deliver order to admin")
        await update.message.reply_text("Не удалось отправить заказ. Попробуйте позже.")
        return ConversationHandler.END
    await update.message.reply_text("Спасибо! 💕 Заказ отправлен продавцу.", reply_markup=menu())
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("Заказ отменён.", reply_markup=menu())
    return ConversationHandler.END


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN environment variable")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(begin_order, pattern=r"^order:")],
        states={
            SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_size)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_order)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(CallbackQueryHandler(show_catalog, pattern=r"^(catalog|outerwear|menu|browse:(?:mayak|monica|cupra|cotton|velour|other|outerwear):[0-9]+)$"))
    app.add_handler(CallbackQueryHandler(show_item, pattern=r"^item:"))
    app.run_polling()


if __name__ == "__main__":
    main()
