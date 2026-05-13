# 🤖 IG CFD Trading Bot — Setup Guide

Built for Simon. Aggressive ASX 200 swing trading via the IG Markets API.

---

## What This Bot Does

- Scans ASX 200, Gold, and Brent Oil CFDs **every 60 seconds**
- Uses an **EMA crossover + RSI** strategy to identify momentum entries
- Automatically opens BUY or SELL positions with stop losses and take profits built in
- Holds a **maximum of 3 positions** at once
- Risks **max 10%** of account per trade with a 1.5% stop / 3.5% target

---

## Step 1: Get Your IG API Key

1. Log into your IG account at [ig.com](https://www.ig.com)
2. Go to **My Account → API**
3. Generate a new API key
4. Note down: your **username**, **password**, **API key**, and **account number**

---

## Step 2: Set Up a Server (Cheap Cloud VPS)

The bot needs to run 24/7. Easiest options:

| Provider | Cost | Link |
|----------|------|------|
| **DigitalOcean Droplet** | ~$6 AUD/month | digitalocean.com |
| **Vultr** | ~$5 AUD/month | vultr.com |
| **AWS Lightsail** | ~$5 AUD/month | aws.amazon.com |

Choose **Ubuntu 22.04** when setting up your server.

---

## Step 3: Install the Bot on Your Server

SSH into your server, then run:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-pip git -y

# Upload the bot files (or copy them across)
# (Use FileZilla, scp, or just paste the code directly)

# Install dependencies
cd ig_trading_bot
pip3 install -r requirements.txt
```

---

## Step 4: Enter Your Credentials

Open `trading_ig/config.py` and fill in:

```python
username   = "your_ig_username"
password   = "your_ig_password"
api_key    = "your_api_key_from_step_1"
acc_type   = "DEMO"          # ← Start with DEMO!
acc_number = "your_account_number"
```

---

## Step 5: Run the Bot

```bash
# Test run (you'll see output in the terminal)
python3 bot.py

# Run in the background (keeps running after you close terminal)
nohup python3 bot.py &

# To see live logs
tail -f trading_bot.log

# To stop the bot
pkill -f bot.py
```

---

## Step 6: Monitor Performance

Watch the log file:
```
tail -f trading_bot.log
```

You'll see entries like:
```
2025-05-13 09:00:01 [INFO] --- Scan #1 | 2025-05-13 09:00:01 UTC ---
2025-05-13 09:00:01 [INFO] Open positions: 0/3
2025-05-13 09:00:03 [INFO] Scanning ASX200 ...
2025-05-13 09:00:04 [INFO]   ASX200: Price=8142.50 | Signal=BUY
2025-05-13 09:00:04 [INFO]   🎯 Signal! BUY ASX200 | Size: 6.5 contracts
2025-05-13 09:00:05 [INFO] ✅ Opened BUY 6.5 contracts of IX.D.ASX.IFM.IP | Stop: 8020.11 | Target: 8427.19
```

---

## Strategy Summary

| Setting | Value |
|---------|-------|
| Markets | ASX 200, Gold, Brent Oil |
| Signal | EMA 9/21 crossover + RSI filter |
| Scan frequency | Every 60 seconds |
| Max positions | 3 at once |
| Risk per trade | 10% of account |
| Stop loss | 1.5% from entry |
| Take profit | 5.0% from entry |
| Reward:Risk | ~3.3:1 |

---

## ⚠️ Important Warnings

- **Always test on DEMO first** — do not switch to LIVE until you've seen consistent results
- CFD trading carries significant risk. You can lose more than you put in with leverage
- Past strategy performance does not guarantee future results
- Monitor the bot regularly — don't just set and forget completely
- IG's API has rate limits (~40 requests/minute) — the bot is built to respect these

---

## Switching to Live Trading

When you're confident in the results:
1. Change `acc_type = "DEMO"` to `acc_type = "LIVE"` in config.py
2. Update your `acc_number` to your live account number
3. Restart the bot

---

*Built with trading-ig Python library and IG Markets REST API*
