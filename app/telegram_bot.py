import asyncio
import telegram
from logging import Logger
from datetime import datetime


class TelegramBot:
    _bot = None
    _chat_id = None
    _logger = None
    _status_message_id = None

    def __init__(self, token: str, chat_id: str, logger: Logger):
        self._bot = telegram.Bot(token=token)
        self._chat_id = chat_id
        self._logger = logger

        self._run_async(self._announce_start)

        self._logger.info("TelegramBot started")

    def _run_async(self, func, *args):
        # Run the async function synchronously
        loop = asyncio.get_event_loop()
        loop.run_until_complete(func(*args))

    async def _announce_start(self):
        # User-facing copy stays in Spanish on purpose (audience reads Spanish)
        await self._bot.send_message(text='DGT ALERT INICIADO', chat_id=self._chat_id)
        await self._unpin_all()
        await self._send_initial_status_message()
        await self._pin_status()

    async def _send_initial_status_message(self):
        current_time = datetime.now().strftime('%H:%M:%S')
        self._status_message_id = (
            await self._bot.send_message(
                text=f'Última Búsqueda: {current_time}',
                chat_id=self._chat_id,
            )
        ).message_id

    async def _pin_status(self):
        await self._bot.pin_chat_message(chat_id=self._chat_id, message_id=self._status_message_id)

    async def _unpin_all(self):
        await self._bot.unpin_all_chat_messages(chat_id=self._chat_id)

    async def _send_result(self, is_approved, screenshot_path):
        # User-facing copy stays in Spanish
        with open(screenshot_path, 'rb') as photo:
            await self._bot.send_photo(
                chat_id=self._chat_id,
                photo=photo,
                caption=f"Resultado: <b>{'APROBADO' if is_approved else 'SUSPENDIDO'}</b> "
                        f"{ '✅' if is_approved else '❌' }",
                parse_mode=telegram.constants.ParseMode.HTML,
            )
        self._logger.info("Photo sent successfully")

    async def _update_alive_status(self):
        current_time = datetime.now().strftime('%H:%M:%S')
        await self._bot.edit_message_text(
            message_id=self._status_message_id,
            text=f'Última Búsqueda: {current_time}',
            chat_id=self._chat_id,
        )

    def send_result(self, is_approved, screenshot_path):
        self._run_async(self._send_result, is_approved, screenshot_path)

    def update_alive_status(self):
        self._run_async(self._update_alive_status)
