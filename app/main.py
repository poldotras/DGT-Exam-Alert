import asyncio
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
import config

from telegram_bot import iniciado, resultado_msg, resultado_imagen, fin, update_funcionando
from datetime import datetime

# Create a persistent event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Configura las opciones de Chrome
opciones = Options()
url = "https://sedeclave.dgt.gob.es/WEB_NOTP_CONSULTA/consultaNota.faces"

# Usa un formato numérico para la hora
hora_inicio = float(datetime.today().strftime('%H.%M'))

exit_flag = False  # Usamos exit_flag en lugar de exit
introduccion_datos = False
resultado_encontrado = False

datos = [config.nif, config.fecha_examen, config.carnet, config.fecha_nacimiento]
ids = [
    "formularioBusquedaNotas:nifnie",
    "formularioBusquedaNotas:fechaExamen",
    "formularioBusquedaNotas:clasepermiso",
    "formularioBusquedaNotas:fechaNacimiento"
]

opciones.add_argument("--log-level=3")
opciones.add_argument("--headless")
opciones.add_argument("--incognito")
# opciones.add_argument("--window-size=1920,1080")
opciones.add_argument("--disable-gpu")
opciones.add_argument("--no-sandbox")

# Inicializa el webdriver
navegador = webdriver.Chrome(options=opciones)
print("Navegador iniciado")
navegador.implicitly_wait(2)

time.sleep(3)
print("Bot iniciado")

# Inicia el bot de Telegram esperando a que la función se ejecute
loop.run_until_complete(iniciado(hora_inicio))

while not exit_flag:
    try:
        navegador.get(url)  # Abre la página
        contador_intentos = 0

        while not introduccion_datos and contador_intentos < 5:
            datos_cont = 0
            for i in range(len(datos)):
                try:
                    navegador.find_element(By.ID, ids[i]).send_keys(datos[i])
                except Exception as e:
                    print(f"\nError al introducir {ids[i]}: {e}")
                else:
                    datos_cont += 1
                time.sleep(3)

            if datos_cont == len(datos):
                introduccion_datos = True
            else:
                # Limpia los datos para reintentar
                navegador.find_element(By.XPATH, "//input[@title='Limpiar']").click()
                print("\nNo se han podido introducir todos los datos")
            contador_intentos += 1

        try:
            hora_actual = datetime.today().strftime('%H:%M')
            navegador.find_element(By.XPATH, "//input[@title='Buscar']").click()
        except Exception as e:
            print("No se ha podido buscar el resultado del examen:", e)
        else:
            while not resultado_encontrado:
                time.sleep(5)
                try:
                    navegador.find_element(By.CLASS_NAME, "msgError")
                except Exception:
                    time.sleep(5)
                    navegador.save_screenshot("resultado.png")
                    time.sleep(3)
                    aprobado_suspenso = navegador.find_element(
                        By.ID, "formularioResultadoNotas:j_id38:0:j_id70"
                    ).text
                    print(aprobado_suspenso)
                    loop.run_until_complete(resultado_msg())
                    loop.run_until_complete(resultado_imagen(aprobado_suspenso))
                    resultado_encontrado = True
                    exit_flag = True
                else:
                    print("\nNo hay resultado - " + hora_actual)
                    # loop.run_until_complete(update_funcionando(hora_actual))
                    time.sleep(config.update_time)
                    continue
    except Exception as e:
        print("Se ha producido un error inesperado:", e)
        exit_flag = False
        introduccion_datos = False
        resultado_encontrado = False
        continue

loop.run_until_complete(fin())
