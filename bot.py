"""Korea Zura Telegram shop bot. Configure via environment variables."""
import json
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    return InlineKeyboardMarkup([[InlineKeyboardButton("👗 Каталог платьев", callback_data="catalog")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Добро пожаловать в Korea Zura! 🛍️ Выберите товар из каталога.",
        reply_markup=menu(),
    )


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    items = catalog()
    if not items:
        await query.message.reply_text("Каталог скоро пополнится! 💕")
        return
    buttons = [
        [InlineKeyboardButton(item["name"], callback_data=f'item:{item["id"]}')]
        for item in items
    ]
    await query.message.reply_text("Выберите модель:", reply_markup=InlineKeyboardMarkup(buttons))


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
    photo = item.get("photo_url")
    if photo:
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
    app.add_handler(CallbackQueryHandler(show_catalog, pattern=r"^catalog$"))
    app.add_handler(CallbackQueryHandler(show_item, pattern=r"^item:"))
    app.run_polling()


if __name__ == "__main__":
    main()
