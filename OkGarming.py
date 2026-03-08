import tkinter as tk
from tkinter import Toplevel, messagebox
from PIL import Image, ImageTk
import os, json, time, threading, winsound, keyboard, tempfile
from vosk import Model, KaldiRecognizer
import pyaudio

# rutas
BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "Assets")
ruta_fondo = os.path.join(ASSETS_DIR, "fondo.png")
ruta_icono = os.path.join(ASSETS_DIR, "icono.ico")
ruta_config = os.path.join(ASSETS_DIR, "config.json")

# asegurar carpeta assets
os.makedirs(ASSETS_DIR, exist_ok=True)

# funcion para escribir json de forma atomica
def escribir_json_atomico(path: str, data: dict):
    dirn = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dirn, prefix="tmpcfg_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise

# cargar config, crear por defecto si no existe o esta mal
def cargar_config():
    default = {"tecla_clip": "f13"}
    if not os.path.exists(ruta_config) or os.path.getsize(ruta_config) == 0:
        escribir_json_atomico(ruta_config, default)
        return default
    try:
        with open(ruta_config, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "tecla_clip" not in data:
                escribir_json_atomico(ruta_config, default)
                return default
            return data
    except (json.JSONDecodeError, OSError):
        escribir_json_atomico(ruta_config, default)
        return default

# cambios para que keyboard entienda
REEMPLAZOS = {
    "control": "ctrl",
    "control_l": "ctrl",
    "control_r": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt_l": "alt",
    "alt_r": "alt",
    "windows_l": "win",
    "windows_r": "win",
    "super": "win",
}

# normaliza un token individual
def normalizar_token(tok: str) -> str:
    t = tok.strip().lower()
    if len(t) == 1:
        return t
    t = t.replace(" ", "_")
    return REEMPLAZOS.get(t, t)

# normaliza la combinacion para guardar (ej: "Ctrl + A" -> "ctrl+a")
def normalizar_combinacion_para_guardar(texto: str) -> str:
    if not texto:
        return ""
    partes = [p.strip() for p in texto.replace("+", " + ").split("+")]
    tokens = [normalizar_token(p) for p in partes if p and p != "+"]
    return "+".join(tokens)

# para keyboard usamos la misma normalizacion
def normalizar_combinacion_para_keyboard(texto: str) -> str:
    return normalizar_combinacion_para_guardar(texto)

# --- interfaz grafica ---
root = tk.Tk()
root.title("Garmin")
root.geometry("200x200")
root.resizable(False, False)

# color de fondo (cambiar si queres otro)
COLOR_FONDO = "#0b0f14"
root.configure(bg=COLOR_FONDO)

# intentar cargar icono .ico, si falla usar la imagen de fondo como icono
try:
    if os.path.exists(ruta_icono):
        root.iconbitmap(ruta_icono)
    else:
        # si no hay .ico, intentar usar el fondo como icono (si existe)
        if os.path.exists(ruta_fondo):
            img_icon = Image.open(ruta_fondo).resize((32, 32))
            root.iconphoto(False, ImageTk.PhotoImage(img_icon))
except Exception:
    pass

# cargar fondo si existe, si no usar color
if os.path.exists(ruta_fondo):
    try:
        fondo_img = Image.open(ruta_fondo).resize((200,200), Image.Resampling.LANCZOS)
        fondo_tk = ImageTk.PhotoImage(fondo_img)
        # canvas con mismo color de fondo y sin borde para evitar marco blanco
        canvas = tk.Canvas(root, width=200, height=200, bg=COLOR_FONDO, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0,0,image=fondo_tk,anchor="nw")
    except Exception:
        root.configure(bg=COLOR_FONDO)
else:
    root.configure(bg=COLOR_FONDO)

# label que muestra la combinacion actual
label_combo = tk.Label(root, text="", bg=COLOR_FONDO, fg="#ffffff")
label_combo.place(x=10, y=170)

def actualizar_label_combo():
    cfg = cargar_config()
    val = cfg.get("tecla_clip", "f13")
    label_combo.config(text=f"Clip: {val.replace('+', ' + ')}")

actualizar_label_combo()

# ventana de configuracion
def abrir_config():
    config_win = Toplevel(root)
    config_win.title("Configuracion")
    config_win.geometry("360x160")
    config_win.resizable(False, False)
    config_win.configure(bg=COLOR_FONDO)

    tk.Label(config_win, text="Presione la combinacion de teclas:", bg=COLOR_FONDO, fg="#fff").pack(pady=(10,4))

    entrada = tk.Entry(config_win, width=30, justify="center", font=("Segoe UI", 12))
    entrada.pack(pady=4)
    entrada.focus_set()

    info_lbl = tk.Label(config_win, text="Presione las teclas; luego haga Guardar", fg="gray", bg=COLOR_FONDO)
    info_lbl.pack()

    pressed = []

    # al presionar una tecla, la agrego a la lista y la muestro
    def on_key(event):
        nonlocal pressed
        key = event.keysym.lower()
        # si el usuario presiona Escape, limpiar la lista
        if key == "escape":
            pressed = []
            entrada.delete(0, tk.END)
            return
        if key not in pressed:
            pressed.append(key)
        entrada.delete(0, tk.END)
        entrada.insert(0, " + ".join(pressed))

    # al guardar tomo el texto del entry, lo normalizo y lo escribo
    def on_guardar():
        texto = entrada.get().strip()
        if not texto:
            messagebox.showwarning("Atencion", "No hay combinacion para guardar.")
            return
        guardado = normalizar_combinacion_para_guardar(texto)
        if not guardado:
            messagebox.showerror("Error", "Combinacion invalida.")
            return
        try:
            escribir_json_atomico(ruta_config, {"tecla_clip": guardado})
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el archivo:\n{e}")
            return
        messagebox.showinfo("Guardado", f"Combinacion guardada: {guardado.replace('+', ' + ')}")
        actualizar_label_combo()
        config_win.destroy()

    # cargar la combinacion actual en el entry
    cfg = cargar_config()
    entrada.insert(0, cfg.get("tecla_clip", "f13").replace("+", " + "))

    config_win.bind("<KeyPress>", on_key)
    btn_guardar = tk.Button(config_win, text="Guardar", width=12, command=on_guardar)
    btn_guardar.pack(pady=10)

# boton de configuracion
btn_config = tk.Button(root, text="⚙️", command=abrir_config, bg="#000", fg="#fff", relief="flat", bd=0)
btn_config.place(x=160, y=10)

# --- reconocimiento de voz en hilo ---
def escuchar():
    ruta_sonido_ok = os.path.join(ASSETS_DIR, "confirm1.wav")
    ruta_sonido_clip = os.path.join(ASSETS_DIR, "clip.wav")

    # cargar modelo
    model = Model("model")
    rec = KaldiRecognizer(model, 16000, '["ok garmin","video station", "che amigo", "che boludo", "ok amigo", "ok boludo"]')

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                    input=True, frames_per_buffer=4000)
    stream.start_stream()
    print("Escuchando...")

    primera_confirmacion = False
    tiempo_confirmacion = None

    while True:
        try:
            data = stream.read(4000, exception_on_overflow=False)
        except Exception:
            continue

        if rec.AcceptWaveform(data):
            try:
                result = json.loads(rec.Result())
            except Exception:
                continue
            texto = result.get("text", "").strip()
            if texto:
                print("Reconocido:", texto)

            if texto == "ok garmin":
                primera_confirmacion = True
                tiempo_confirmacion = time.time()
                if os.path.exists(ruta_sonido_ok):
                    winsound.PlaySound(ruta_sonido_ok, winsound.SND_FILENAME)

            elif primera_confirmacion and texto == "video station":
                print("¡Clip guardado!")
                # leer siempre del json 
                cfg = cargar_config()
                raw = cfg.get("tecla_clip", "f13")
                combo = normalizar_combinacion_para_keyboard(raw.replace(" + ", "+"))
                try:
                    keyboard.press_and_release(combo)
                except Exception as e:
                    print("Error al enviar la combinacion con keyboard:", e)
                if os.path.exists(ruta_sonido_clip):
                    winsound.PlaySound(ruta_sonido_clip, winsound.SND_FILENAME)
                primera_confirmacion = False
                tiempo_confirmacion = None

        # timeout 
        if primera_confirmacion and tiempo_confirmacion:
            if time.time() - tiempo_confirmacion > 5:
                print("Reiniciando confirmacion...")
                primera_confirmacion = False
                tiempo_confirmacion = None

# iniciar hilo de escucha
threading.Thread(target=escuchar, daemon=True).start()

root.mainloop()

