import logging
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import config

logger = logging.getLogger(__name__)

class TelegramAuthManager:
    """
    Manages the state of the Telegram client and its authentication flow.
    This replaces the simple singleton to handle a multi-step, non-interactive sign-in.
    """
    _client = None
    _phone_code_hash = None
    _phone = None

    @classmethod
    def get_instance(cls):
        if cls._client is None:
            cls._client = TelegramClient(
                'leadcore_session',
                config.TELEGRAM_API_ID,
                config.TELEGRAM_API_HASH,
                # The connection is managed manually now
                auto_reconnect=True
            )
        return cls

    @classmethod
    async def get_client(cls) -> TelegramClient:
        instance = cls.get_instance()
        if not instance._client.is_connected():
            logger.info("Connecting to Telegram...")
            await instance._client.connect()
        return instance._client

    @classmethod
    async def is_authorized(cls) -> bool:
        client = await cls.get_client()
        return await client.is_user_authorized()

    @classmethod
    async def start_sign_in(cls, phone: str) -> None:
        client = await cls.get_client()
        cls._phone = phone
        try:
            result = await client.send_code_request(phone)
            cls._phone_code_hash = result.phone_code_hash
            logger.info(f"Sent code request to {phone}")
        except Exception as e:
            logger.error(f"Failed to send code request: {e}")
            raise

    @classmethod
    async def submit_code(cls, code: str) -> str:
        client = await cls.get_client()
        if not cls._phone or not cls._phone_code_hash:
            raise ValueError("Sign-in process not started. Call start_sign_in first.")
        
        try:
            await client.sign_in(cls._phone, code, phone_code_hash=cls._phone_code_hash)
            logger.info("Sign-in with code successful.")
            return "signed_in"
        except SessionPasswordNeededError:
            logger.info("Password needed to complete sign-in.")
            return "password_needed"
        except Exception as e:
            logger.error(f"Failed to sign in with code: {e}")
            raise

    @classmethod
    async def submit_password(cls, password: str) -> None:
        client = await cls.get_client()
        try:
            await client.sign_in(password=password)
            logger.info("Sign-in with password successful.")
        except Exception as e:
            logger.error(f"Failed to sign in with password: {e}")
            raise
    
    @classmethod
    async def disconnect(cls):
        if cls._client and cls._client.is_connected():
            logger.info("Disconnecting Telegram client...")
            await cls._client.disconnect()

# Custom exception for signaling auth requirement
class AuthorizationRequiredError(Exception):
    pass
