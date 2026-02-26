import requests
from datetime import datetime, timedelta
import asyncio
from zoneinfo import ZoneInfo  # Київський час
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes, CommandHandler

# ---------------- Налаштування ----------------
ICS_URL = "https://outlook.office365.com/owa/calendar/79c642b8b6ca43da9b6fbc07e91d6e3f@stu.cn.ua/bbe9ebf86117463999fb8318dbd44e0c18278536239716574951/calendar.ics"
TELEGRAM_TOKEN = "8684962421:AAFwN72b29u0zBkzPvsoN8A_zWpg6Up3XlM"
NOTIFY_CHAT_ID = -1003084376120   # нова група
NOTIFY_THREAD_ID = 3891           # розділ "Пари"
KYIV_TZ = ZoneInfo("Europe/Kiev")

# ---------------- ICS парсер ----------------
def clean_description(desc):
    desc = desc.replace("\r\n ", "").replace("\\,", ",").replace("\\n", "\n").strip()
    lines = desc.split("\n")
    filtered_lines = []
    for line in lines:
        if any(k in line for k in ["Microsoft Teams", "Присоединиться", "Идентификатор", "Секретный код", "Нарада"]):
            filtered_lines.append(line.strip())
    if not filtered_lines and desc:
        filtered_lines.append(desc.splitlines()[0].strip())
    return "\n".join(filtered_lines)

def get_events_for_date(year, month, day):
    try:
        response = requests.get(ICS_URL)
        text = response.text.replace("\r\n ", "")
        events_raw = text.split("BEGIN:VEVENT")
        target_date = datetime(year, month, day, tzinfo=KYIV_TZ).date()
        events = []
        for block in events_raw:
            if "DTSTART" in block and "SUMMARY" in block:
                try:
                    start_line = [l for l in block.splitlines() if "DTSTART" in l][0]
                    dt = datetime.strptime(start_line.split(":")[1][:15], "%Y%m%dT%H%M%S")
                    dt = dt.replace(tzinfo=KYIV_TZ)  # Київський час
                    if dt.date() != target_date:
                        continue
                    name_line = [l for l in block.splitlines() if "SUMMARY" in l][0]
                    name_text = name_line.split(":",1)[1].strip()
                    desc_lines = [l for l in block.splitlines() if l.startswith("DESCRIPTION")]
                    desc_text = clean_description(":".join(desc_lines[0].split(":",1)[1:])) if desc_lines else "Деталі відсутні"
                    events.append({"title": f"{dt.strftime('%H:%M')} | {name_text}", "details": desc_text, "time": dt})
                except:
                    continue
        return events
    except:
        return []

# ---------------- Telegram команди ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = datetime.now(KYIV_TZ)
    events = get_events_for_date(target_date.year, target_date.month, target_date.day)

    context.user_data["events"] = events
    context.user_data["date"] = target_date

    if not events:
        await update.message.reply_text(f"Подій на {target_date.strftime('%d.%m.%Y')} немає")
        return

    buttons = [[InlineKeyboardButton(event["title"], callback_data=f"event_{i}")] for i, event in enumerate(events)]
    buttons.append([InlineKeyboardButton("📅 Обрати інший день", callback_data="choose_day")])
    keyboard = InlineKeyboardMarkup(buttons)

    msg = await update.message.reply_text(f"📅 Події на Сьогодні ({target_date.strftime('%d.%m')}):", reply_markup=keyboard)
    context.user_data["main_msg_id"] = msg.message_id

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    main_msg_id = context.user_data.get("main_msg_id")

    if data.startswith("event_"):
        idx = int(data.split("_")[1])
        events = context.user_data.get("events", [])
        if idx >= len(events):
            await query.edit_message_text("Помилка: подія не знайдена")
            return
        event = events[idx]
        new_text = f"{event['title']}\n\n{event['details']}"

        last_text = context.user_data.get("last_text")
        detail_msg_id = context.user_data.get("detail_msg_id")

        if last_text != new_text:
            if detail_msg_id:
                try:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=detail_msg_id, text=new_text)
                except:
                    pass
            else:
                msg = await context.bot.send_message(chat_id=chat_id, text=new_text)
                context.user_data["detail_msg_id"] = msg.message_id

            context.user_data["last_text"] = new_text

    elif data == "choose_day":
        detail_msg_id = context.user_data.get("detail_msg_id")
        if detail_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=detail_msg_id)
            except:
                pass
            context.user_data["detail_msg_id"] = None
            context.user_data["last_text"] = None

        today = datetime.now(KYIV_TZ).date()
        day_buttons = []
        for offset in [-2, -1, 0, 1, 2]:
            d = today + timedelta(days=offset)
            if d == today:
                label = f"Сьогодні ({d.strftime('%d.%m')})"
            else:
                label = d.strftime('%d.%m')
            day_buttons.append([InlineKeyboardButton(label, callback_data=f"day_{d}")])
        keyboard = InlineKeyboardMarkup(day_buttons)

        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=main_msg_id, text="Обери день:", reply_markup=keyboard)
        except:
            pass

    elif data.startswith("day_"):
        day_str = data.split("_")[1]
        selected_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        events = get_events_for_date(selected_date.year, selected_date.month, selected_date.day)
        context.user_data["events"] = events
        context.user_data["date"] = selected_date
        context.user_data["detail_msg_id"] = None
        context.user_data["last_text"] = None

        if not events:
            new_text = f"Подій на {selected_date.strftime('%d.%m.%Y')} немає"
            buttons = [[InlineKeyboardButton("📅 Обрати інший день", callback_data="choose_day")]]
        else:
            buttons = [[InlineKeyboardButton(event["title"], callback_data=f"event_{i}")] for i, event in enumerate(events)]
            buttons.append([InlineKeyboardButton("📅 Обрати інший день", callback_data="choose_day")])
            if selected_date == datetime.now(KYIV_TZ).date():
                new_text = f"📅 Події на Сьогодні ({selected_date.strftime('%d.%m')}):"
            else:
                new_text = f"📅 Події на {selected_date.strftime('%d.%m.%Y')}:"  

        keyboard = InlineKeyboardMarkup(buttons)
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=main_msg_id, text=new_text, reply_markup=keyboard)
        except:
            pass

# ---------------- Фоновий цикл сповіщень ----------------
sent_messages = []  # одне повідомлення на чат

# ---------------- Фоновий цикл сповіщень ----------------
sent_messages = []

async def notification_loop(bot):
    sent_events = set()
    while True:
        now = datetime.now(KYIV_TZ)
        events = get_events_for_date(now.year, now.month, now.day)

        for event in events:
            notify_time = event["time"] - timedelta(minutes=10)
            key = (event["title"], event["time"])

            if key in sent_events:
                continue

            if notify_time <= now < notify_time + timedelta(seconds=60):
                try:
                    # Видаляємо старе повідомлення
                    if sent_messages:
                        for msg_id in sent_messages:
                            try:
                                await bot.delete_message(
                                    chat_id=NOTIFY_CHAT_ID,
                                    message_id=msg_id
                                )
                            except:
                                pass
                        sent_messages.clear()

                    # Відправка в конкретний розділ (topic)
                    msg = await bot.send_message(
                        chat_id=NOTIFY_CHAT_ID,
                        message_thread_id=NOTIFY_THREAD_ID,
                        text=(
                            f"⏰ Через 10 хвилин початок пари:\n"
                            f"{event['title']}\n"
                            f"{event['details']}\n\n"
                            f"Більше інформації:"
                            f" https://t.me/Microsoft_Canendar_Bot?start=start"
                        )
                    )

                    sent_messages.append(msg.message_id)
                    sent_events.add(key)

                except Exception as e:
                    print("Помилка сповіщення:", e)

        await asyncio.sleep(30)

# ------------------ Запуск бота ------------------
# ------------------ Запуск бота ------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))

    print("Бот запущено...")

    # Запускаємо фоновий цикл через JobQueue
    app.job_queue.run_repeating(
        lambda context: notification_loop(context.bot),
        interval=30,
        first=5,
    )

    app.run_polling()
