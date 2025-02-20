import asyncio
import telegram
from datetime import datetime
import config

token = config.telegram_bot_token
chat_id = config.chat_id
bot = telegram.Bot(token=token)

async def iniciado(hora_inicio):
    await bot.send_message(text='Buscador de resultados iniciado', chat_id=chat_id)
    await unpin()
    await funcionando(hora_inicio)
    await pin()

async def resultado_msg():
    await bot.send_message(text='¡Resultado del Examen encontrado!', chat_id=chat_id)

async def resultado_imagen(pass_fail):
    with open('resultado.png', 'rb') as photo:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=f"Resultado:\n{pass_fail}")
    print("\nFoto enviada correctamente")

async def update_funcionando(hora_actual):
    await bot.edit_message_text(message_id=funcionando_msg.message_id, text=f'Última Búsqueda: {hora_actual}', chat_id=chat_id)

async def funcionando(hora_actual):
    global funcionando_msg
    funcionando_msg = await bot.send_message(text=f'Última Búsqueda: {hora_actual}', chat_id=chat_id)

async def fin():
    await bot.send_message(text='Programa Finalizado', chat_id=chat_id)

async def pin():
    await bot.pin_chat_message(chat_id=chat_id, message_id=funcionando_msg.message_id)

async def unpin():
    await bot.unpin_all_chat_messages(chat_id=chat_id)

# Para ejecutar una prueba o iniciar el flujo principal
if __name__ == "__main__":
    asyncio.run(iniciado(datetime.today().strftime('%H.%M')))