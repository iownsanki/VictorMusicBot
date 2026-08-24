import os
import asyncio
from pyrogram import Client

print("=" * 50)
print("  PYROGRAM STRING SESSION GENERATOR FOR ASSISTANT")
print("=" * 50)

async def main():
    api_id = 39647605
    api_hash = "a345f32e05b0aa70e91f87e98bb5b287"

    app = Client("temp_session_gen", in_memory=True, api_id=api_id, api_hash=api_hash)
    async with app:
        session_str = await app.export_session_string()
        print("\n" + "=" * 50)
        print("SUCCESS! YOUR SESSION STRING:")
        print("=" * 50)
        print(session_str)
        print("=" * 50)
        
        # Auto-update .env file
        env_path = "c:\\Users\\pydev\\Documents\\TELEGRAM\\.env"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            content = re.sub(r"SESSION_STRING=.*", f"SESSION_STRING={session_str}", content)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("\n[OK] Automatically updated SESSION_STRING inside .env file!")

if __name__ == "__main__":
    asyncio.run(main())
