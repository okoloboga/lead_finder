import asyncio
import logging
from modules.telegram_client import TelegramAuthManager
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    """
    This script performs a one-time interactive login to create a valid
    Telethon session file (`leadsense_session.session`).

    Run this script directly on your local machine (not in Docker).
    Telethon will prompt you to enter your phone number, the code you receive,
    and your 2FA password (if you have one) directly in the console.

    Once the `leadsense_session.session` file is created, the main bot
    application running inside Docker will be able to use it without needing
    to log in again.
    """
    print("Attempting to connect to Telegram to create a session file...")
    
    client = await TelegramAuthManager.get_client()

    if not await client.is_user_authorized():
        print("User is not authorized. Starting interactive sign-in...")
        print("You may be prompted for your phone, code, and password (if any).")
        # This will trigger the interactive prompts in the console
        await client.start(phone=config.TELEGRAM_PHONE)
    
    # Verify authorization after attempting to start
    if await client.is_user_authorized():
        print("\nSuccessfully connected and authorized!")
        print("A 'leadsense_session.session' file has been created/updated.")
        print("You can now stop this script (Ctrl+C) and run the main bot with 'docker compose up --build -d'.")
    else:
        print("\nSomething went wrong during authorization. Please check your credentials and try again.")

    # Keep the connection alive to ensure the session file is fully written
    await client.disconnect()
    print("\nSession file saved. Script finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Session generation script stopped.")