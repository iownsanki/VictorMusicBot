# Victor VC Music Bot (Railway Ready)

### ?? Railway Deployment Steps:
1. Create a new GitHub repo and push this folder (or use Railway CLI).
2. On Railway (railway.app): Click **+ New Project** -> **Deploy from GitHub repo**.
3. Go to **Variables** tab on Railway and add the following:
   - API_ID
   - API_HASH
   - BOT_TOKEN
   - SESSION_STRING
   - OWNER_ID
   - SUDO_USERS
4. Railway will automatically build using Dockerfile with FFmpeg pre-installed and start the bot!
