import os
import sys
import shutil
import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Auto-configure FFmpeg binary path if not already in system PATH
try:
    if not shutil.which("ffmpeg"):
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_bin)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        # Also create a copy/symlink named ffmpeg.exe if needed
        ffmpeg_alias = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(ffmpeg_alias):
            try:
                shutil.copyfile(ffmpeg_bin, ffmpeg_alias)
            except Exception:
                pass
except Exception as e:
    pass

import yt_dlp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, Update
from pytgcalls.exceptions import NoActiveGroupCall

import config

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("VCMusicBot")

# Initialize Pyrogram Bot & Assistant Clients
bot = Client(
    "VCMusicBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True
)

assistant = Client(
    "VCAssistant",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.SESSION_STRING,
    in_memory=True
)

pytgcalls = PyTgCalls(assistant)

# Queue storage: chat_id -> list of song dicts
# song dict: {"title": str, "duration": str, "url": str, "stream_url": str, "file_path": str, "requester": str}
music_queues: Dict[int, List[dict]] = defaultdict(list)
current_playing: Dict[int, dict] = {}

# yt-dlp configuration
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "nocheckcertificate": True,
}


def search_ytdl(query: str) -> Optional[dict]:
    """Search YouTube or extract stream info for a given query/URL."""
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
        try:
            if not query.startswith(("http://", "https://")):
                query = f"ytsearch:{query}"
            info = ytdl.extract_info(query, download=False)
            if "entries" in info:
                if not info["entries"]:
                    return None
                info = info["entries"][0]

            stream_url = info.get("url")
            # In case url is not direct, grab the best audio format url
            if not stream_url and "formats" in info:
                for f in info["formats"]:
                    if f.get("acodec") != "none" and (f.get("vcodec") == "none" or not f.get("vcodec")):
                        stream_url = f.get("url")
                        break
                if not stream_url:
                    stream_url = info["formats"][-1].get("url")

            duration_secs = int(info.get("duration", 0))
            mins, secs = divmod(duration_secs, 60)
            duration_str = f"{mins:02d}:{secs:02d}"

            return {
                "title": info.get("title", "Unknown Title"),
                "duration": duration_str,
                "url": info.get("webpage_url", query),
                "stream_url": stream_url,
                "file_path": None,
            }
        except Exception as err:
            logger.error(f"yt-dlp extract error: {err}")
            return None


async def start_stream(chat_id: int):
    """Start playing the current song in queue for chat_id."""
    if not music_queues[chat_id]:
        current_playing.pop(chat_id, None)
        try:
            await pytgcalls.leave_call(chat_id)
        except Exception:
            pass
        return

    track = music_queues[chat_id][0]
    current_playing[chat_id] = track
    media_source = track["file_path"] or track["stream_url"]

    stream = MediaStream(
        media_source,
        audio_parameters=AudioQuality.HIGH,
        ytdlp_parameters=YTDL_OPTIONS.get("default_search", "")
    )

    try:
        await pytgcalls.play(chat_id, stream)
    except Exception as e:
        logger.warning(f"Error in play, attempting to change_stream: {e}")
        try:
            await pytgcalls.play(chat_id, stream)
        except Exception as ex:
            logger.error(f"Failed to play stream: {ex}")


@pytgcalls.on_update()
async def stream_update_handler(_, update: Update):
    """Handle stream ending event and play next queued track."""
    # When stream ends
    try:
        from pytgcalls.types import StreamEnded
        if isinstance(update, StreamEnded):
            chat_id = update.chat_id
            if chat_id in music_queues and music_queues[chat_id]:
                # Remove played song
                old_track = music_queues[chat_id].pop(0)
                if old_track.get("file_path") and os.path.exists(old_track["file_path"]):
                    try:
                        os.remove(old_track["file_path"])
                    except Exception:
                        pass

                if music_queues[chat_id]:
                    await start_stream(chat_id)
                    next_track = music_queues[chat_id][0]
                    await bot.send_message(
                        chat_id,
                        f"🎶 **Now Playing Next Track:**\n"
                        f"📌 **Title:** `{next_track['title']}`\n"
                        f"⏱ **Duration:** `{next_track['duration']}`\n"
                        f"👤 **Requested by:** {next_track['requester']}"
                    )
                else:
                    current_playing.pop(chat_id, None)
                    await pytgcalls.leave_call(chat_id)
                    await bot.send_message(chat_id, "✅ **Queue finished. Assistant left the Voice Chat.**")
    except Exception as e:
        logger.error(f"Stream update error: {e}")


async def ensure_assistant_in_chat(chat_id: int, message: Message) -> bool:
    """Ensure that the assistant userbot is present in the group chat."""
    try:
        assistant_user = await assistant.get_me()
        try:
            member = await bot.get_chat_member(chat_id, assistant_user.id)
            if member.status in [ChatMemberStatus.BANNED, ChatMemberStatus.RESTRICTED]:
                await message.reply_text("❌ **Assistant is banned/restricted in this group! Unban assistant first.**")
                return False
            return True
        except Exception:
            pass

        # 1. Try to directly add assistant to the group
        try:
            await bot.add_chat_members(chat_id, assistant_user.id)
            await asyncio.sleep(1)
            return True
        except Exception:
            pass

        # 2. Try exporting invite link and having assistant join
        try:
            chat = await bot.get_chat(chat_id)
            if chat.username:
                await assistant.join_chat(chat.username)
                return True
            invite_link = await bot.export_chat_invite_link(chat_id)
            await assistant.join_chat(invite_link)
            return True
        except Exception as ex:
            logger.warning(f"Auto-join assistant failed: {ex}")
            await message.reply_text(
                f"⚠️ **Assistant (@{assistant_user.username or assistant_user.first_name}) ko auto-add nahi kar paya.**\n"
                f"Kripya bot ko Group me **Invite Users / Add Members** admin permission dein, ya Assistant ko manually group me add karein."
            )
            return False
    except Exception as e:
        logger.error(f"Assistant verification failed: {e}")
        return False


# ==========================================
#              BOT COMMANDS
# ==========================================

@bot.on_message(filters.command(["start", "help"], prefixes=config.COMMAND_PREFIXES))
async def start_handler(_, message: Message):
    text = (
        "🎵 **Welcome to Telegram VC Music Bot!**\n\n"
        "**Available Commands:**\n"
        "• `/play <song name or link>` : Play music in group VC (or reply to audio)\n"
        "• `/pause` : Pause the active stream\n"
        "• `/resume` : Resume the paused stream\n"
        "• `/skip` : Skip to the next song in queue\n"
        "• `/end` or `/leavevc` : Stop music & leave VC\n"
        "• `/queue` : Show active music queue\n"
        "• `/volume <1-200>` : Adjust assistant stream volume\n"
        "• `/ping` : Check bot & assistant latency"
    )
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Bot to Group", url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true")]
        ])
    )


@bot.on_message(filters.command(["ping"], prefixes=config.COMMAND_PREFIXES))
async def ping_handler(_, message: Message):
    import time
    start = time.time()
    msg = await message.reply_text("🏓 **Pinging...**")
    delta_ms = round((time.time() - start) * 1000, 2)
    await msg.edit_text(f"🏓 **Pong!** `{delta_ms}ms`\n🤖 **Bot & Assistant Online!**")


@bot.on_message(filters.command(["play", "p"], prefixes=config.COMMAND_PREFIXES))
async def play_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command sirf Groups ke liye hai!**\n\nMujhe apne Group me add karein, VC on karein aur wahan `/play <song>` likhein.")
        return
    chat_id = message.chat.id
    query = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""

    # Check if replying to an audio file
    replied_audio = None
    if message.reply_to_message:
        if message.reply_to_message.audio or message.reply_to_message.voice:
            replied_audio = message.reply_to_message.audio or message.reply_to_message.voice

    if not query and not replied_audio:
        await message.reply_text("❓ **Usage:** `/play <song name or YouTube link>` or reply `/play` to an audio file.")
        return

    status_msg = await message.reply_text("🔎 **Searching & Preparing track...**")

    # Ensure assistant is in the group
    if not await ensure_assistant_in_chat(chat_id, message):
        await status_msg.delete()
        return

    track_info = None

    if replied_audio:
        await status_msg.edit_text("📥 **Downloading audio file...**")
        file_path = await message.reply_to_message.download()
        duration_secs = replied_audio.duration or 0
        mins, secs = divmod(duration_secs, 60)
        track_info = {
            "title": getattr(replied_audio, "file_name", "Telegram Audio"),
            "duration": f"{mins:02d}:{secs:02d}",
            "url": message.reply_to_message.link or "",
            "stream_url": None,
            "file_path": file_path,
            "requester": message.from_user.mention if message.from_user else "Anonymous"
        }
    else:
        loop = asyncio.get_running_loop()
        track_info = await loop.run_in_executor(None, search_ytdl, query)
        if not track_info:
            await status_msg.edit_text("❌ **No results found on YouTube! Try another song name.**")
            return
        track_info["requester"] = message.from_user.mention if message.from_user else "Anonymous"

    # Add to queue
    music_queues[chat_id].append(track_info)

    if len(music_queues[chat_id]) == 1:
        # Start immediately
        await status_msg.edit_text("🚀 **Connecting Assistant to VC and starting stream...**")
        try:
            await start_stream(chat_id)
            await status_msg.edit_text(
                f"🎶 **Playing in VC:**\n"
                f"📌 **Title:** [{track_info['title']}]({track_info.get('url', '')})\n"
                f"⏱ **Duration:** `{track_info['duration']}`\n"
                f"👤 **Requested by:** {track_info['requester']}",
                disable_web_page_preview=True
            )
        except NoActiveGroupCall:
            music_queues[chat_id].clear()
            await status_msg.edit_text("❌ **No active Voice Chat found in this group! Please start the group VC first.**")
        except Exception as e:
            music_queues[chat_id].clear()
            logger.error(f"Play exception: {e}")
            await status_msg.edit_text(f"❌ **Error starting playback:** `{e}`")
    else:
        position = len(music_queues[chat_id]) - 1
        await status_msg.edit_text(
            f"📋 **Added to Queue (Position #{position}):**\n"
            f"📌 **Title:** [{track_info['title']}]({track_info.get('url', '')})\n"
            f"⏱ **Duration:** `{track_info['duration']}`\n"
            f"👤 **Requested by:** {track_info['requester']}",
            disable_web_page_preview=True
        )


@bot.on_message(filters.command(["pause"], prefixes=config.COMMAND_PREFIXES))
async def pause_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    try:
        await pytgcalls.pause(chat_id)
        await message.reply_text("⏸ **Stream paused!** Use `/resume` to continue.")
    except Exception as e:
        await message.reply_text(f"❌ **Error pausing stream:** `{e}`")


@bot.on_message(filters.command(["resume"], prefixes=config.COMMAND_PREFIXES))
async def resume_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    try:
        await pytgcalls.resume(chat_id)
        await message.reply_text("▶️ **Stream resumed!**")
    except Exception as e:
        await message.reply_text(f"❌ **Error resuming stream:** `{e}`")


@bot.on_message(filters.command(["skip", "next"], prefixes=config.COMMAND_PREFIXES))
async def skip_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    if chat_id not in music_queues or not music_queues[chat_id]:
        await message.reply_text("❌ **Nothing is playing to skip!**")
        return

    old_track = music_queues[chat_id].pop(0)
    if old_track.get("file_path") and os.path.exists(old_track["file_path"]):
        try:
            os.remove(old_track["file_path"])
        except Exception:
            pass

    if music_queues[chat_id]:
        await start_stream(chat_id)
        next_track = music_queues[chat_id][0]
        await message.reply_text(
            f"⏭ **Skipped! Now playing:**\n"
            f"📌 **Title:** `{next_track['title']}`\n"
            f"⏱ **Duration:** `{next_track['duration']}`"
        )
    else:
        current_playing.pop(chat_id, None)
        try:
            await pytgcalls.leave_call(chat_id)
        except Exception:
            pass
        await message.reply_text("⏭ **Skipped! Queue is now empty, Assistant left VC.**")


@bot.on_message(filters.command(["end", "stop", "leavevc", "disconnect"], prefixes=config.COMMAND_PREFIXES))
async def end_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    music_queues[chat_id].clear()
    current_playing.pop(chat_id, None)
    try:
        await pytgcalls.leave_call(chat_id)
        await message.reply_text("⏹ **Stopped playback, cleared queue, and left Voice Chat!**")
    except Exception as e:
        await message.reply_text(f"⏹ **Stream ended and queue cleared.**")


@bot.on_message(filters.command(["queue", "q"], prefixes=config.COMMAND_PREFIXES))
async def queue_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    if chat_id not in music_queues or not music_queues[chat_id]:
        await message.reply_text("📭 **Queue is currently empty.**")
        return

    msg = "📜 **Current Music Queue:**\n\n"
    for i, track in enumerate(music_queues[chat_id]):
        status = "▶️ [Playing]" if i == 0 else f"`#{i}`"
        msg += f"{status} **{track['title']}** (`{track['duration']}`) - req by {track['requester']}\n"

    await message.reply_text(msg)


@bot.on_message(filters.command(["volume", "vol"], prefixes=config.COMMAND_PREFIXES))
async def volume_handler(_, message: Message):
    if message.chat.type.value in ["private"]:
        await message.reply_text("⚠️ **Yeh command Group Voice Chat ke liye hai!**")
        return
    chat_id = message.chat.id
    if len(message.command) < 2:
        await message.reply_text("❓ **Usage:** `/volume <1-200>`")
        return

    try:
        vol = int(message.command[1])
        if not (1 <= vol <= 200):
            await message.reply_text("⚠️ **Volume must be between 1 and 200!**")
            return
        await pytgcalls.change_volume_call(chat_id, vol)
        await message.reply_text(f"🔊 **Volume set to:** `{vol}%`")
    except Exception as e:
        await message.reply_text(f"❌ **Failed to change volume:** `{e}`")


# ==========================================
#              RUN BOT & ASSISTANT
# ==========================================

async def main():
    if not config.BOT_TOKEN or not config.SESSION_STRING or config.API_ID == 0:
        print("\n" + "!" * 60)
        print("ERROR: Please fill in API_ID, API_HASH, BOT_TOKEN, and SESSION_STRING")
        print("in config.py or in your .env file before running!")
        print("Run 'python generate_session.py' to generate SESSION_STRING for assistant.")
        print("!" * 60 + "\n")
        return

    print("🚀 Starting Bot & Assistant Userbot...")
    await bot.start()
    await assistant.start()
    await pytgcalls.start()

    bot_me = await bot.get_me()
    ass_me = await assistant.get_me()

    print("=" * 50)
    print(f"✅ Bot Started: @{bot_me.username} [{bot_me.id}]")
    print(f"✅ Assistant Started: @{ass_me.username or ass_me.first_name} [{ass_me.id}]")
    print("🎵 VC Music Bot is ready to stream!")
    print("=" * 50)

    # Permanent event loop keep-alive
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("Stopping services...")
        try:
            await pytgcalls.stop()
        except Exception:
            pass
        try:
            await assistant.stop()
        except Exception:
            pass
        try:
            await bot.stop()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
