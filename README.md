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

## Deploy 24/7 on an Oracle Cloud VM

GitHub stores the source code but does not run the bot. An Oracle Cloud VM can
keep it running continuously when an Always Free-eligible VM is available in
your region and within your account's Always Free limits. Check the Oracle
console's eligibility and billing details before creating resources.

1. Create an Ubuntu VM in Oracle Cloud and note its public IP address. In its
   network security rules, allow inbound SSH (TCP port 22) only from your own
   IP address. This polling bot needs outbound HTTPS (TCP port 443); it does
   not need an inbound application port.
2. From PowerShell, connect using the SSH private key you selected when
   creating the VM:

   ```powershell
   ssh -i "C:\path\to\your-private-key" ubuntu@YOUR_VM_PUBLIC_IP
   ```

3. In the VM's SSH session, install Python and download the project:

   ```bash
   sudo apt update
   sudo apt install -y git python3 python3-venv
   sudo useradd --system --user-group --create-home --home-dir /home/tripbot --shell /usr/sbin/nologin tripbot
   sudo git clone https://github.com/mikiyasassefa/trip-telegrambot.git /opt/trip-telegrambot
   sudo chown -R tripbot:tripbot /opt/trip-telegrambot
   sudo -u tripbot python3 -m venv /opt/trip-telegrambot/.venv
   sudo -u tripbot /opt/trip-telegrambot/.venv/bin/pip install -r /opt/trip-telegrambot/requirements.txt
   ```

4. Create a root-only environment file and enter your **new** bot token and
   numeric admin ID:

   ```bash
   sudo install -o root -g root -m 600 /dev/null /etc/trip-telegrambot.env
   sudo nano /etc/trip-telegrambot.env
   ```

   Put these two lines in the file (replace the values):

   ```text
   BOT_TOKEN=YOUR_NEW_BOT_TOKEN
   ADMIN_ID=YOUR_NUMERIC_TELEGRAM_ID
   ```

   Save and exit nano with `Ctrl+O`, `Enter`, then `Ctrl+X`. Never put real
   credentials in GitHub.

5. Install and enable the service so it starts on boot and restarts if it
   crashes:

   ```bash
   sudo cp /opt/trip-telegrambot/deploy/trip-telegrambot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now trip-telegrambot
   sudo systemctl status trip-telegrambot --no-pager
   ```

   View live logs with:

   ```bash
   sudo journalctl -u trip-telegrambot -f
   ```

6. Stop the bot on your Windows PC before starting the VM service if both use
   the same token. Only one polling process should run for a bot token.

To update the deployed code later:

```bash
sudo systemctl stop trip-telegrambot
sudo -u tripbot git -C /opt/trip-telegrambot pull
sudo -u tripbot /opt/trip-telegrambot/.venv/bin/pip install -r /opt/trip-telegrambot/requirements.txt
sudo systemctl start trip-telegrambot
```

## Data and deployment

The bot creates `orders.db` next to the script. It stores orders and trip edits,
so keep this file on persistent storage and back it up securely. Do not publish
it; it contains customer information. On the VM it is stored at
`/opt/trip-telegrambot/orders.db`; back it up securely. VM restarts preserve the
disk, but deleting the VM or its disk can permanently delete orders and trip
edits.
