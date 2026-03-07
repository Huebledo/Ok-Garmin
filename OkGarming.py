from vosk import Model, KaldiRecognizer
import pyaudio
import json
import time
import winsound
import os
import keyboard

# Ruta de sonidos 
ruta_sonido_ok = os.path.join(os.path.dirname(__file__), "Assets", "confirm1.wav")
ruta_sonido_clip = os.path.join(os.path.dirname(__file__), "Assets", "clip.wav")

# Ruta del modelo
model = Model("model")

# Diccionario 
rec = KaldiRecognizer(model, 16000, '["ok garmin", "ok chabon", "che chabon", "video station"]')

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                input=True, frames_per_buffer=4000)
stream.start_stream()

print("Escuchando...")

# Estados
primera_confirmacion = False
tiempo_confirmacion = None

while True:
    try:
        data = stream.read(4000, exception_on_overflow=False)
    except IOError:
        
        continue

    if rec.AcceptWaveform(data):
        result = json.loads(rec.Result())
        texto = result.get("text", "").strip()
        print("Reconocido:", texto)

        # Primera palabra clave
        if texto == "ok garmin":
            primera_confirmacion = True
            tiempo_confirmacion = time.time()
            print("Primera confirmación detectada: ok garmin")
            winsound.PlaySound(ruta_sonido_ok, winsound.SND_FILENAME)

        # Segunda palabra clave
        elif primera_confirmacion and texto == "video station":
            print("¡Clip guardado!")
            keyboard.press_and_release("f16") #placeholder
            winsound.PlaySound(ruta_sonido_clip, winsound.SND_FILENAME)
            primera_confirmacion = False
            tiempo_confirmacion = None

    # Limite de tiempo
    if primera_confirmacion and tiempo_confirmacion:
        if time.time() - tiempo_confirmacion > 5:
            print("reiniciando confirmacion...")
            primera_confirmacion = False
            tiempo_confirmacion = None
