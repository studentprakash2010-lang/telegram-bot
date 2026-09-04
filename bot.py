import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8878883602:AAFF7cAPag1QF9R7xsxGEWSItuvBoi6Ub3I"
ADMIN_IDS = [8919217555, 7689771634, 6709007742]

# Replace with your direct image link (e.g., from Imgur, PostImages, or your website)
QR_IMAGE_URL = "https://ibb.co/dJwTyFv7"

bot = telebot.TeleBot(BOT_TOKEN)

# Tracks which admin is replying to which user: {admin_chat_id: target_user_id}
admin_reply_state = {}

# --- Keyboards ---

def get_main_menu():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("1. Main ID Safe Panel", callback_data="safe_panel"),
        InlineKeyboardButton("2. Main ID Unsafe Panel", callback_data="unsafe_panel")
    )
    return markup

def get_safe_menu():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("1. Bala Mode", callback_data="bala_mode"),
        InlineKeyboardButton("2. Permanent Panel", callback_data="perm_panel")
    )
    markup.add(InlineKeyboardButton("« Back", callback_data="back_main"))
    return markup

def get_bala_menu():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("1 Hour - ₹20", callback_data="pay_Bala 1 Hour_20"),
        InlineKeyboardButton("2 Hour - ₹35", callback_data="pay_Bala 2 Hour_35")
    )
    markup.add(
        InlineKeyboardButton("4 Hour - ₹75", callback_data="pay_Bala 4 Hour_75"),
        InlineKeyboardButton("1 Day - ₹450", callback_data="pay_Bala 1 Day_450")
    )
    markup.add(InlineKeyboardButton("« Back", callback_data="safe_panel"))
    return markup

def get_permanent_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Ninza Plus - ₹500", callback_data="pay_Ninza Plus_500"))
    markup.add(InlineKeyboardButton("« Back", callback_data="safe_panel"))
    return markup

def get_unsafe_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Unsafe Panel Access - ₹100", callback_data="pay_Unsafe Panel_100"))
    markup.add(InlineKeyboardButton("« Back", callback_data="back_main"))
    return markup

def get_payment_keyboard(order_details):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(" Done / Paid", callback_data=f"done_{order_details}"))
    markup.add(InlineKeyboardButton("« Cancel", callback_data="back_main"))
    return markup

# --- Handlers ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        "Welcome! Please select an option below:",
        reply_markup=get_main_menu()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    if data == "back_main":
        bot.edit_message_text("Please select an option below:", chat_id, message_id, reply_markup=get_main_menu())

    elif data == "safe_panel":
        bot.edit_message_text("Main ID Safe Panel selected. Choose category:", chat_id, message_id, reply_markup=get_safe_menu())

    elif data == "unsafe_panel":
        bot.edit_message_text("Main ID Unsafe Panel selected:", chat_id, message_id, reply_markup=get_unsafe_menu())

    elif data == "bala_mode":
        bot.edit_message_text("Select duration for Bala Mode:", chat_id, message_id, reply_markup=get_bala_menu())

    elif data == "perm_panel":
        bot.edit_message_text("Select Permanent Panel option:", chat_id, message_id, reply_markup=get_permanent_menu())

    elif data.startswith("pay_"):
        _, item_name, price = data.split("_")
        caption = f"Selected: *{item_name}*\nPrice: *₹{price}*\n\nScan the QR code below to pay. Tap *Done* once payment is complete."
        
        try:
            bot.send_photo(
                chat_id,
                photo=QR_IMAGE_URL,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=get_payment_keyboard(f"{item_name}:{price}")
            )
        except Exception:
            bot.send_message(
                chat_id,
                f"{caption}\n\n*(Could not load QR. Please verify the URL)*",
                parse_mode="Markdown",
                reply_markup=get_payment_keyboard(f"{item_name}:{price}")
            )

    elif data.startswith("done_"):
        order_info = data.replace("done_", "")
        bot.send_message(chat_id, " Thank you! Your payment notification has been sent to the admins. Please wait for confirmation.")
        
        username = f"@{call.from_user.username}" if call.from_user.username else "No Username"
        admin_markup = InlineKeyboardMarkup()
        admin_markup.add(InlineKeyboardButton("Reply to User", callback_data=f"reply_{call.from_user.id}"))
        
        admin_msg = (
            f" *New Order Received*\n"
            f"• User: {call.from_user.first_name} ({username})\n"
            f"• User ID: `{call.from_user.id}`\n"
            f"• Item: {order_info.split(':')[0]}\n"
            f"• Amount: ₹{order_info.split(':')[1]}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, admin_msg, parse_mode="Markdown", reply_markup=admin_markup)
            except Exception as e:
                print(f"Failed to alert admin {admin_id}: {e}")

    elif data.startswith("reply_"):
        target_user_id = int(data.replace("reply_", ""))
        admin_reply_state[call.from_user.id] = target_user_id
        bot.send_message(call.from_user.id, f"Type the message you want to deliver to user `{target_user_id}`:")

# --- Admin Reply Handler ---

@bot.message_handler(func=lambda msg: msg.chat.id in ADMIN_IDS and msg.chat.id in admin_reply_state)
def forward_admin_reply(message):
    target_user_id = admin_reply_state.pop(message.chat.id)
    try:
        bot.send_message(target_user_id, f" *Admin Update:*\n\n{message.text}", parse_mode="Markdown")
        bot.send_message(message.chat.id, f" Message delivered to `{target_user_id}` successfully.")
    except Exception as e:
        bot.send_message(message.chat.id, f" Failed to deliver message: {str(e)}")

if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()
    
