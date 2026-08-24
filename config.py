import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
#         TELEGRAM VC MUSIC BOT CONFIG
# ==========================================

# Telegram API credentials from https://my.telegram.org
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Main Bot Token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Assistant / Userbot Pyrogram V2 Session String
# (Run python generate_session.py to generate this string)
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Command prefixes (e.g. ['/', '!', '.'])
COMMAND_PREFIXES = ["/", "!", "."]

# Owner & Sudo User IDs (integers)
SUDO_USERS = [
    int(x) for x in os.getenv("SUDO_USERS", "").split() if x.isdigit()
]
