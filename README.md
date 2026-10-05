# Telegram Trip Booking Bot

A Telegram bot for trip bookings, payment screenshot review, and ticket delivery.

## Setup

1. Install Python 3.10 or newer.
2. Install dependencies:

   ```powershell
   py -m pip install -r requirements.txt
   ```

3. Create or regenerate the bot token with [@BotFather](https://t.me/BotFather).
   Set the token and the admin's numeric Telegram user ID in the same PowerShell
   session used to start the bot:

   ```powershell
   $env:BOT_TOKEN = "YOUR_NEW_BOT_TOKEN"
   $env:ADMIN_ID = "YOUR_NUMERIC_TELEGRAM_ID"
   py .\ticket_bot.py
   ```

   Do not commit the token, `.env` files, or `orders.db`.

## Admin commands

- `/admin` lists admin commands.
- `/pending` lists payments awaiting review.
- `/trips` displays trip details.
- `/edittrip` lets the admin update a trip's name, date, price, description,
  or photo through Telegram.

Start a private chat with the bot from the admin account before it needs to
send you messages.

## Data and deployment

The bot creates `orders.db` next to the script. It stores orders and trip edits,
so keep this file on persistent storage and back it up securely. Do not publish
it; it contains customer information.

GitHub stores the source code but does not keep the bot running. For continuous
uptime, run `ticket_bot.py` as a continuously running worker on a computer or
hosting service. Configure `BOT_TOKEN` and `ADMIN_ID` as environment variables
there, and provide persistent storage for `orders.db`.
