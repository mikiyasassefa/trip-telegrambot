import logging
import os
import sqlite3

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# =====================  SETTINGS - EDIT THIS PART  =====================

TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# Your own Telegram numeric ID (get it from @userinfobot).
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", ""))
except ValueError:
    ADMIN_ID = 0

# The list of trips users can choose from.
# "photo" is the picture file name. Put the pictures in a folder called
# "photos" next to this file (for example photos/lalibela.jpg).
# You can also use a web link that starts with https://
# If the photo is missing, the trip is shown as text only.
TRIPS = [
    {
        "name": " ወደ ዝቋላ አቡነ ገብረመንፈስ ቅዱስ ገዳም",
        "date": "መነሻ ጥቅምት4 መመለሻ ጥቅምት 5 2019",
        "price": "1200 ETB",
        "description": (
            "የ አባታችን የአቡነ ገብረ መንፈስ ቅዱስ በዓለ እረፍታቸውን ከደብራችን በ78 ኪ.ሜ. ርቀት ላይ በሚገኘው"
            " በምስራቅ ሸዋ ሀገረ ስብከት የ ዝቋላ አቡነ ገብረ መንፈስ ቅዱስ ገዳም ከ ሰንበት ትምህርት ቤታችን ጉዞ ክፍል ጋር አብረው ያሳልፉ."
        ),
        "photo": "photos/zkuala.webp",
    },
]

# Shown to the user after they pick a trip.
BANK_DETAILS = (
    "Bank: Commercial Bank of Ethiopia\n"
    "Account name: Your Company Name\n"
    "Account number: 1000123456789"
)

# How many hours you promise customers to answer within.
ADMIN_RESPONSE_HOURS = 12
# The bot reminds YOU (the admin) if a payment is still waiting after this many hours.
REMIND_ADMIN_AFTER_HOURS = 8

DB_FILE = "orders.db"

# =======================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# httpx logs every request URL, which contains your bot token. Silence it.
logging.getLogger("httpx").setLevel(logging.WARNING)

NAME, PHONE, TRIP, SCREENSHOT = range(4)


# ----------------------------- Database ------------------------------

def db_init():
    with sqlite3.connect(DB_FILE) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                name TEXT,
                phone TEXT,
                trip TEXT,
                price TEXT,
                status TEXT,
                ticket_number TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        # Add new columns if this is an older orders.db file.
        for col in ("paid_at TIMESTAMP", "reminded INTEGER DEFAULT 0"):
            try:
                db.execute(f"ALTER TABLE orders ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # column already exists
        db.execute(
            """CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                date TEXT NOT NULL,
                price TEXT NOT NULL,
                description TEXT NOT NULL,
                photo TEXT NOT NULL DEFAULT ''
            )"""
        )
        db.executemany(
            "INSERT OR IGNORE INTO trips (id, name, date, price, description, photo) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    i,
                    trip["name"],
                    trip["date"],
                    trip["price"],
                    trip["description"],
                    trip.get("photo", ""),
                )
                for i, trip in enumerate(TRIPS)
            ],
        )


def db_get_trips():
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute("SELECT * FROM trips ORDER BY id").fetchall()
        ]


def db_get_trip(trip_id):
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        return dict(row) if row else None


def db_update_trip(trip_id, field, value):
    if field not in {"name", "date", "price", "description", "photo"}:
        raise ValueError(f"Unsupported trip field: {field}")
    with sqlite3.connect(DB_FILE) as db:
        cursor = db.execute(
            f"UPDATE trips SET {field} = ? WHERE id = ?", (value, trip_id)
        )
        return cursor.rowcount > 0


def db_create_order(user_id, username, name, phone, trip, price):
    with sqlite3.connect(DB_FILE) as db:
        cur = db.execute(
            "INSERT INTO orders (user_id, username, name, phone, trip, price, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_payment')",
            (user_id, username, name, phone, trip, price),
        )
        return cur.lastrowid


def db_get_order(order_id):
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        return db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def db_set_status(order_id, status, ticket_number=None):
    with sqlite3.connect(DB_FILE) as db:
        db.execute(
            "UPDATE orders SET status = ?, "
            "ticket_number = COALESCE(?, ticket_number), "
            "paid_at = CASE WHEN ? = 'pending_review' THEN CURRENT_TIMESTAMP ELSE paid_at END "
            "WHERE id = ?",
            (status, ticket_number, status, order_id),
        )


def db_pending():
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            "SELECT *, (julianday('now') - julianday(paid_at)) * 24 AS hours_waiting "
            "FROM orders WHERE status = 'pending_review' ORDER BY id"
        ).fetchall()


def db_due_for_reminder(hours):
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            "SELECT * FROM orders WHERE status = 'pending_review' AND reminded = 0 "
            "AND paid_at IS NOT NULL "
            "AND (julianday('now') - julianday(paid_at)) * 24 >= ?",
            (hours,),
        ).fetchall()


def db_mark_reminded(order_id):
    with sqlite3.connect(DB_FILE) as db:
        db.execute("UPDATE orders SET reminded = 1 WHERE id = ?", (order_id,))


# --------------------------- User conversation -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "እንኳን ደህና መጡ! 🙏 የጉዞ ትኬትዎን አብረን እንቁረጥ.\n\n"
        "በመጀመሪያ ሙሉ ስምዎትን ያስገቡ:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("እባክዎ ሙሉ ስምዎትን ያስገቡ:")
        return NAME
    context.user_data["name"] = name

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Share my phone number", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "አመሰናለሁ። ከዚህ በመቀጠል ስልክ ቁጥርዎትን ያስገቡ .\n"
        "Tap the button below, or just type it.",
        reply_markup=keyboard,
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 9:
        await update.message.reply_text("እባኮትን ትክክለኛ ስልክ ቁጥር ያስገቡ:")
        return PHONE
    context.user_data["phone"] = phone

    await update.message.reply_text(
        " ✅ አሁን ላይ ያዘጋጀነው ጉዞ ከታች ተያይዟል  ", reply_markup=ReplyKeyboardRemove()
    )

    base_dir = os.path.dirname(os.path.abspath(__file__))
    for t in db_get_trips():
        caption = (
            f"📍 {t['name']}\n"
            f"📅 {t['date']}\n"
            f"💰 {t['price']}\n\n"
            f"{t['description']}"
        )[:1024]  # Telegram's limit for photo captions
        button = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Choose this trip", callback_data=f"trip_{t['id']}")]]
        )

        photo = t.get("photo", "")
        sent = False
        if photo.startswith("http"):
            try:
                await update.message.reply_photo(photo, caption=caption, reply_markup=button)
                sent = True
            except TelegramError as e:
                logging.warning("Could not send photo link for %s: %s", t["name"], e)
        elif photo.startswith("tg:"):
            try:
                await update.message.reply_photo(
                    photo[3:], caption=caption, reply_markup=button
                )
                sent = True
            except TelegramError as e:
                logging.warning("Could not send Telegram photo for %s: %s", t["name"], e)
        elif photo and os.path.exists(os.path.join(base_dir, photo)):
            with open(os.path.join(base_dir, photo), "rb") as f:
                await update.message.reply_photo(f, caption=caption, reply_markup=button)
            sent = True

        if not sent:  # no photo found, send as plain text
            await update.message.reply_text(caption, reply_markup=button)

    return TRIP


async def choose_trip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    trip = db_get_trip(int(query.data.split("_")[1]))
    if trip is None:
        await query.edit_message_text("Sorry, this trip is no longer available.")
        return ConversationHandler.END
    user = query.from_user
    order_id = db_create_order(
        user.id,
        user.username,
        context.user_data["name"],
        context.user_data["phone"],
        trip["name"],
        trip["price"],
    )
    context.user_data["order_id"] = order_id

    await context.bot.send_message(
        query.message.chat_id,
        f"የመረጡት ጉዞ: {trip['name']}\n"
        f"የጉዞ ቀን: {trip['date']}\n"
        f"ዋጋ: {trip['price']}\n\n"
        f"እባኮትን ከላይ የተጠቀሰውን ይጉዞውን ክፍያ ያስገቡ:\n\n{BANK_DETAILS}\n\n"
        f"ከከፈሉ በኋላ screenshot እዚሁ ላይ ይላኩ📸\n"
        f"(Confirmation can take up to {ADMIN_RESPONSE_HOURS} hours.)\n"
        f"(Send /cancel to stop.)"
    )
    return SCREENSHOT


async def get_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    order_id = context.user_data["order_id"]
    order = db_get_order(order_id)

    caption = (
        f"🧾 New payment - Order #{order_id}\n"
        f"Name: {order['name']}\n"
        f"Phone: {order['phone']}\n"
        f"Telegram: @{order['username'] or 'no username'}\n"
        f"Trip: {order['trip']}\n"
        f"Price: {order['price']}"
    )
    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order_id}"),
            ]
        ]
    )

    try:
        if msg.photo:
            await context.bot.send_photo(
                ADMIN_ID, msg.photo[-1].file_id, caption=caption, reply_markup=buttons
            )
        else:
            await context.bot.send_document(
                ADMIN_ID, msg.document.file_id, caption=caption, reply_markup=buttons
            )
    except TelegramError as e:
        logging.error("Could not forward screenshot to admin: %s", e)
        await msg.reply_text(
            "Sorry, there was a connection problem. 😔\n"
            "Please send the screenshot again."
        )
        return SCREENSHOT  # stay here so the user can retry

    db_set_status(order_id, "pending_review")
    await msg.reply_text(
        "Thank you! 🙏 We received your payment screenshot.\n\n"
        f"⏳ Our admin will verify it and send your ticket number here "
        f"within {ADMIN_RESPONSE_HOURS} hours. Please wait, and you will get a "
        f"message in this chat as soon as your ticket is ready."
    )
    return ConversationHandler.END


async def screenshot_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send the payment screenshot as a photo, or /cancel to stop."
    )
    return SCREENSHOT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Cancelled. Send /start whenever you want to book again.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ------------------------------ Admin --------------------------------

TRIP_FIELDS = {
    "name": "trip name",
    "date": "trip date",
    "price": "price",
    "description": "description",
    "photo": "photo",
}


def trip_selection_keyboard(trips):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Edit trip {i + 1}: {trip['name'][:35]}",
                    callback_data=f"admin_trip_{trip['id']}",
                )
            ]
            for i, trip in enumerate(trips)
        ]
    )


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not configured as the admin for this bot.")
        return
    await update.message.reply_text(
        "Admin commands:\n"
        "/pending - view payments awaiting review\n"
        "/trips - view trip information\n"
        "/edittrip - choose a trip and update its name, date, price, description, or photo"
    )


async def admin_trips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not configured as the admin for this bot.")
        return

    trips = db_get_trips()
    if not trips:
        await update.message.reply_text("No trips are configured.")
        return

    lines = [
        f"Trip {i + 1}\n"
        f"Name: {trip['name']}\n"
        f"Date: {trip['date']}\n"
        f"Price: {trip['price']}\n"
        f"Description: {trip['description']}\n"
        f"Photo: {'set' if trip['photo'] else 'not set'}"
        for i, trip in enumerate(trips)
    ]
    await update.message.reply_text(
        "\n\n".join(lines),
        reply_markup=trip_selection_keyboard(trips),
    )


async def admin_edit_trip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not configured as the admin for this bot.")
        return

    trips = db_get_trips()
    if not trips:
        await update.message.reply_text("No trips are configured.")
        return
    await update.message.reply_text(
        "Choose a trip to edit:",
        reply_markup=trip_selection_keyboard(trips),
    )


async def admin_trip_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Admins only.", show_alert=True)
        return
    await query.answer()

    parts = query.data.split("_")
    if parts[1] == "trip":
        trip = db_get_trip(int(parts[2]))
        if trip is None:
            await query.edit_message_text("That trip is no longer available.")
            return

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        label.capitalize(),
                        callback_data=f"admin_field_{trip['id']}_{field}",
                    )
                ]
                for field, label in TRIP_FIELDS.items()
            ]
        )
        await query.edit_message_text(
            f"Editing trip: {trip['name']}\n"
            "Choose the information to change:",
            reply_markup=keyboard,
        )
        return

    trip_id, field = int(parts[2]), parts[3]
    if field not in TRIP_FIELDS or db_get_trip(trip_id) is None:
        await query.edit_message_text("That trip or field is no longer available.")
        return

    context.user_data["editing_trip"] = {"id": trip_id, "field": field}
    input_hint = (
        "Send a photo in Telegram as an image (not as a file), or send an image URL."
        if field == "photo"
        else f"Send the new {TRIP_FIELDS[field]} as a message."
    )
    await query.edit_message_text(
        f"{input_hint}\nUse /cancel_edit to stop without saving."
    )


async def admin_trip_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edit = context.user_data.get("editing_trip")
    if not edit:
        return

    value = update.message.text.strip()
    if not value:
        await update.message.reply_text("That value can't be empty. Please try again.")
        return

    if edit["field"] == "photo":
        if not value.startswith(("http://", "https://")):
            await update.message.reply_text(
                "Please upload the image as a Telegram photo, or send a photo URL."
            )
            return

    if not db_update_trip(edit["id"], edit["field"], value):
        context.user_data.pop("editing_trip", None)
        await update.message.reply_text("That trip no longer exists. Send /edittrip to try again.")
        return

    context.user_data.pop("editing_trip", None)
    await update.message.reply_text(
        f"Trip {TRIP_FIELDS[edit['field']]} updated successfully. "
        "Send /trips to review it."
    )


async def admin_trip_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edit = context.user_data.get("editing_trip")
    if not edit or edit["field"] != "photo":
        return

    file_id = update.message.photo[-1].file_id
    if not db_update_trip(edit["id"], "photo", f"tg:{file_id}"):
        context.user_data.pop("editing_trip", None)
        await update.message.reply_text(
            "That trip no longer exists. Send /edittrip to try again."
        )
        return

    context.user_data.pop("editing_trip", None)
    await update.message.reply_text(
        "Trip photo updated successfully. Send /trips to review it."
    )


async def cancel_trip_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("editing_trip", None)
    await update.message.reply_text("Trip edit cancelled; no changes were saved.")


async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the Approve / Reject buttons under the screenshot."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Admins only.", show_alert=True)
        return
    await query.answer()

    action, order_id = query.data.split("_")
    order_id = int(order_id)
    order = db_get_order(order_id)
    if order is None:
        return

    if action == "approve":
        context.user_data["awaiting_ticket"] = order_id
        await query.edit_message_caption(
            f"✅ Order #{order_id} approved ({order['name']}).\n\n"
            f"Now type the TICKET NUMBER and send it. I'll deliver it to the customer."
        )
    else:
        db_set_status(order_id, "rejected")
        await query.edit_message_caption(f"❌ Order #{order_id} rejected ({order['name']}).")
        await context.bot.send_message(
            order["user_id"],
            "ይቅርታ ክፍያዎን ማረጋገጥ አልተቻለም. 😔\n"
            "እባኮትን ክፍያዎን አረጋግጠው ደግመው ይሞክሩ"
            "or contact us for help.",
        )


async def admin_ticket_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin types the ticket number after approving."""
    order_id = context.user_data.get("awaiting_ticket")
    if not order_id:
        return  # nothing to do, ignore normal messages

    ticket = update.message.text.strip()
    order = db_get_order(order_id)
    db_set_status(order_id, "ticketed", ticket)
    context.user_data.pop("awaiting_ticket")

    await context.bot.send_message(
        order["user_id"],
        f"🙏 አመሰግናለሁ , {order['name']}! ክፍያው በተሳካ ሁኔታ ተጠናቋል።\n\n"
        f"Trip: {order['trip']}\n"
        f"🎫 የትኬት ቁጥሮ: {ticket}\n\n"
        f"እባኮትን ይህን ቁጥር በጥንቃቄ ይያዙ።መልካም ጉዞ ይሁንሎት!",
    )
    await update.message.reply_text(
        f"Ticket {ticket} sent to {order['name']} (order #{order_id}) ✅"
    )


async def admin_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("editing_trip"):
        await admin_trip_edit_input(update, context)
    else:
        await admin_ticket_number(update, context)


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not configured as the admin for this bot.")
        return
    rows = db_pending()
    if not rows:
        await update.message.reply_text("No pending payments 🎉")
        return
    lines = []
    for r in rows:
        h = r["hours_waiting"]
        waited = f"{h:.1f}h waiting" if h is not None else "time unknown"
        warn = " ⚠️" if h is not None and h >= ADMIN_RESPONSE_HOURS - 2 else ""
        lines.append(f"#{r['id']} - {r['name']} - {r['phone']} - {r['trip']} - {waited}{warn}")
    await update.message.reply_text(
        "Pending payments (scroll up to the screenshot and tap Approve/Reject):\n"
        + "\n".join(lines)
    )


async def remind_admin(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 30 minutes and reminds the admin about old pending payments."""
    for r in db_due_for_reminder(REMIND_ADMIN_AFTER_HOURS):
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"⏰ Reminder: order #{r['id']} ({r['name']}, {r['trip']}) has been "
                f"waiting more than {REMIND_ADMIN_AFTER_HOURS} hours.\n"
                f"Customers are promised an answer within {ADMIN_RESPONSE_HOURS} hours.\n"
                f"Scroll up to the screenshot and tap Approve or Reject, "
                f"or send /pending to see all.",
            )
            db_mark_reminded(r["id"])
        except TelegramError as e:
            logging.error("Could not send reminder: %s", e)


# ------------------------------- Main --------------------------------

def main():
    if not TOKEN:
        raise RuntimeError("Set the BOT_TOKEN environment variable before starting the bot.")
    if ADMIN_ID <= 0:
        raise RuntimeError("Set ADMIN_ID to your numeric Telegram user ID before starting the bot.")

    db_init()
    app = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(60)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )

    async def on_error(update, context):
        logging.error("Error: %s", context.error)

    app.add_error_handler(on_error)

    booking = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [
                MessageHandler(filters.CONTACT, get_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
            ],
            TRIP: [CallbackQueryHandler(choose_trip, pattern=r"^trip_\d+$")],
            SCREENSHOT: [
                CallbackQueryHandler(choose_trip, pattern=r"^trip_\d+$"),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, get_screenshot),
                MessageHandler(filters.ALL & ~filters.COMMAND, screenshot_reminder),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app.add_handler(booking)
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("trips", admin_trips))
    app.add_handler(CommandHandler("edittrip", admin_edit_trip))
    app.add_handler(CommandHandler("cancel_edit", cancel_trip_edit))
    app.add_handler(
        CallbackQueryHandler(admin_trip_editor, pattern=r"^admin_(trip|field)_")
    )
    app.add_handler(CallbackQueryHandler(admin_buttons, pattern=r"^(approve|reject)_\d+$"))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID), admin_text_message
        )
    )
    app.add_handler(
        MessageHandler(
            filters.PHOTO & filters.User(ADMIN_ID), admin_trip_photo_input
        )
    )

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()