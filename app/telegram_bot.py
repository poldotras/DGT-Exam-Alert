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

        self._run_async(self._iniciado)

        self._logger.info("TelegramBot Iniciado")
        
    def _run_async(self, func, *args):
        # Ejecuta la función asíncrona de manera síncrona
        loop = asyncio.get_event_loop()
        loop.run_until_complete(func(*args))

    async def _iniciado(self):
        await self._bot.send_message(text='DGT ALERT INICIADO', chat_id=self._chat_id)
        await self._unpin()
        await self._first_status_message()
        await self._pin()

    async def _first_status_message(self):
        hora_actual = datetime.now().strftime('%H:%M:%S')
        self._status_message_id = (await self._bot.send_message(text=f'Última Búsqueda: {hora_actual}', chat_id=self._chat_id)).message_id

    async def _pin(self):
        await self._bot.pin_chat_message(chat_id=self._chat_id, message_id=self._status_message_id)

    async def _unpin(self):
        await self._bot.unpin_all_chat_messages(chat_id=self._chat_id)

    async def _resultado(self, is_apto, screenshot_path):
        with open(screenshot_path, 'rb') as photo:
            await self._bot.send_photo(chat_id=self._chat_id, photo=photo, caption=f"Resultado: <b>{'APROBADO' if is_apto else 'SUSPENDIDO'}</b> { '✅' if is_apto else '❌' }", parse_mode=telegram.constants.ParseMode.HTML)
        self._logger.info("Foto enviada correctamente")

    async def _update_funcionando(self):
        hora_actual = datetime.now().strftime('%H:%M:%S')
        await self._bot.edit_message_text(message_id=self._status_message_id, text=f'Última Búsqueda: {hora_actual}', chat_id=self._chat_id)

    def resultado(self, is_apto, screenshot_path):
        self._run_async(self._resultado, is_apto, screenshot_path)
    
    def update_funcionando(self):
        self._run_async(self._update_funcionando)