import tkinter as tk
from tkinter import Toplevel, messagebox
from PIL import Image, ImageTk
import os, json, time, threading, winsound, keyboard, tempfile
from vosk import Model, KaldiRecognizer
import pyaudio
import re

# rutas
BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "Assets")
ruta_fondo = os.path.join(ASSETS_DIR, "fondo.png")
ruta_icono = os.path.join(ASSETS_DIR, "icono.ico")
ruta_config = os.path.join(ASSETS_DIR, "config.json")
ruta_frases = os.path.join(ASSETS_DIR, "phrases.json")

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

def crear_phrases_por_defecto():
    default = ["ok garmin", "video station", "che amigo", "che boludo", "ok amigo", "ok boludo"]
    if not os.path.exists(ruta_frases) or os.path.getsize(ruta_frases) == 0:
        escribir_json_atomico(ruta_frases, default)
    return default

def cargar_frases():
    crear_phrases_por_defecto()
    try:
        with open(ruta_frases, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list) and all(isinstance(x, str) for x in data) and len(data) >= 2:
                return data
    except Exception:
        pass
    # si algo falla, devolver default y reescribir
    default = ["ok garmin", "video station", "che amigo", "che boludo", "ok amigo", "ok boludo"]
    try:
        escribir_json_atomico(ruta_frases, default)
    except Exception:
        pass
    return default

# ventana para editar phrases.json
def abrir_editor_frases():
    win = Toplevel(root)
    win.title("Editar frases")
    # abrir maximizada (Windows: 'zoomed'; en otros OS puede funcionar también)
    try:
        win.state('zoomed')
    except Exception:
        # fallback: usar geometry con tamaño de pantalla
        w = root.winfo_screenwidth()
        h = root.winfo_screenheight()
        win.geometry(f"{w}x{h}+0+0")
    win.resizable(True, True)
    win.configure(bg=COLOR_FONDO)
    tk.Label(win, text="Esta es la lista de palabras registradas. Cada palabra minimamente similar se va a convertir en alguna de estas.", bg=COLOR_FONDO, fg="#fff").pack(pady=(8,4))

    text = tk.Text(win, wrap="none", bg="#111", fg="#fff", insertbackground="#fff")
    text.pack(fill="both", expand=True, padx=8, pady=6)

    # cargar contenido actual
    frases = cargar_frases()
    text.delete("1.0", tk.END)
    text.insert("1.0", json.dumps(frases, ensure_ascii=False, indent=4))

    info = tk.Label(win, text="Las primeras 2 palabras son las clave. Recordar que el modelo entiende principalmente ingles. Segui el formato o te va a tirar error.", fg="White", bg=COLOR_FONDO)
    info.pack(pady=(4,6))

    def on_guardar_frases():
        contenido = text.get("1.0", tk.END).strip()
        try:
            data = json.loads(contenido)
            if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
                raise ValueError("El JSON debe ser una lista de cadenas.")
            if len(data) < 2:
                raise ValueError("Debe haber al menos 2 frases (clave1 y clave2).")
        except Exception as e:
            messagebox.showerror("Error", f"JSON inválido:\n{e}")
            return
        try:
            escribir_json_atomico(ruta_frases, data)
            messagebox.showinfo("Guardado", "Frases guardadas correctamente.")
            win.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")

    btn = tk.Button(win, text="Guardar", width=12, command=on_guardar_frases)
    btn.pack(pady=8)

# crear botón en la ventana principal para abrir editor de frases

# cargar config, crear por defecto si no existe o esta mal
def cargar_config():
    default = {"tecla_clip": "f13", "cooldown": 5}
    if not os.path.exists(ruta_config) or os.path.getsize(ruta_config) == 0:
        escribir_json_atomico(ruta_config, default)
        return default
    try:
        with open(ruta_config, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "tecla_clip" not in data:
                escribir_json_atomico(ruta_config, default)
                return default
            # asegurar que cooldown exista y sea numérico
            if "cooldown" not in data or not isinstance(data.get("cooldown"), (int, float)):
                data["cooldown"] = default["cooldown"]
                escribir_json_atomico(ruta_config, data)
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
    cd = int(cfg.get("cooldown", 5))
    label_combo.config(text=f"Botón: {val.replace('+', ' + ')}   CD: {cd}s")

actualizar_label_combo()

def abrir_cooldown():
    win = Toplevel(root)
    win.title("Cooldown")
    win.geometry("300x140")
    win.resizable(False, False)
    win.configure(bg=COLOR_FONDO)

    tk.Label(win, text="Cooldown en segundos (Valor entero):", bg=COLOR_FONDO, fg="#fff").pack(pady=(12,6))

    entrada_cd = tk.Entry(win, width=10, justify="center", font=("Segoe UI", 12))
    entrada_cd.pack()

    info = tk.Label(win, text="Cuanto tiempo para decir la 2da frase luego de la 1ra.", fg="gray", bg=COLOR_FONDO)
    info.pack(pady=(6,4))

    # cargar valor actual
    cfg = cargar_config()
    entrada_cd.insert(0, str(int(cfg.get("cooldown", 5))))

    def on_guardar_cd():
        val = entrada_cd.get().strip()
        try:
            n = int(val)
            if n < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Ingrese un número entero mayor o igual a 1.")
            return
        # actualizar config sin perder otras claves
        cfg2 = cargar_config()
        cfg2["cooldown"] = n
        try:
            escribir_json_atomico(ruta_config, cfg2)
            actualizar_label_combo()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
            return
        messagebox.showinfo("Guardado", f"Cooldown guardado: {n} segundos")
        win.destroy()

    btn = tk.Button(win, text="Guardar", width=12, command=on_guardar_cd)
    btn.pack(pady=8)

# crear botón en la ventana principal (colócalo donde prefieras)
btn_cd = tk.Button(root, text="Cooldown", command=abrir_cooldown, bg="#000", fg="#fff", relief="flat", bd=0)
btn_cd.place(x=100, y=10)



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

    # estructura nueva: modifiers (set) y main_key (str)
    modifiers = set()
    main_key = ""

    # orden canonico para mostrar modificadores
    MOD_ORDER = ["ctrl", "alt", "shift", "win"]

    def construir_texto():
        parts = []
        # ordenar modificadores según MOD_ORDER
        for m in MOD_ORDER:
            if m in modifiers:
                parts.append(m)
        # añadir cualquier otro modificador no listado (por si aparece)
        for m in sorted(modifiers):
            if m not in MOD_ORDER:
                parts.append(m)
        if main_key:
            parts.append(main_key)
        # mostrar con mayúscula inicial en letras y con " + "
        display = " + ".join(parts)
        return display

    # al presionar una tecla, actualizo modifiers/main_key y muestro
    def on_key(event):
        nonlocal modifiers, main_key
        key_raw = event.keysym  # usar keysym original para distinguir BackSpace, Delete, etc.
        key_norm = normalizar_token(key_raw.lower())

        # Escape: limpiar todo
        if key_raw == "Escape":
            modifiers.clear()
            main_key = ""
            entrada.delete(0, tk.END)
            return

        # Delete: limpiar todo
        if key_raw in ("Delete", "Del"):
            modifiers.clear()
            main_key = ""
            entrada.delete(0, tk.END)
            return

        # BackSpace: borrar main_key si existe, sino borrar ultimo modificador
        if key_raw in ("BackSpace", "BackSpace"):
            if main_key:
                main_key = ""
            else:
                # eliminar ultimo modificador según orden inverso de MOD_ORDER
                removed = None
                for m in reversed(MOD_ORDER):
                    if m in modifiers:
                        removed = m
                        break
                if not removed and modifiers:
                    # si no hay en MOD_ORDER, eliminar cualquiera (sorted para determinismo)
                    removed = sorted(modifiers)[-1]
                if removed:
                    modifiers.discard(removed)
            entrada.delete(0, tk.END)
            entrada.insert(0, construir_texto())
            return

        # detectar si es modificador (usando normalizacion)
        if key_norm in ("ctrl", "shift", "alt", "win"):
            modifiers.add(key_norm)
            entrada.delete(0, tk.END)
            entrada.insert(0, construir_texto())
            return

        # ignorar teclas puramente de modificador que no normalizamos (ej: Control_L ya manejado)
        # si es una tecla imprimible o especial (space, f1..f12, etc.) la tomo como main_key
        # normalizar espacios y nombres comunes
        if key_norm == "space":
            main_key = "space"
        else:
            main_key = key_norm

        entrada.delete(0, tk.END)
        entrada.insert(0, construir_texto())

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

    # cargar la combinacion actual en el entry (y poblar modifiers/main_key)
    cfg = cargar_config()
    current = cfg.get("tecla_clip", "f13")
    entrada.insert(0, current.replace("+", " + "))

    # inicializar modifiers/main_key desde la config para que BackSpace funcione correctamente
    partes = [p.strip() for p in current.split("+") if p.strip()]
    modifiers.clear()
    main_key = ""
    for p in partes:
        tok = normalizar_token(p)
        if tok in ("ctrl", "alt", "shift", "win"):
            modifiers.add(tok)
        else:
            main_key = tok

    # enlazar keypress a la ventana de configuracion (captura combinaciones)
    config_win.bind("<KeyPress>", on_key)
    btn_guardar = tk.Button(config_win, text="Guardar", width=12, command=on_guardar)
    btn_guardar.pack(pady=10)


# boton de configuracion
btn_config = tk.Button(root, text="⚙️", command=abrir_config, bg="#000", fg="#fff", relief="flat", bd=0)
btn_config.place(x=160, y=10)

btn_frases = tk.Button(root, text="Frases", command=abrir_editor_frases, bg="#000", fg="#fff", relief="flat", bd=0)
btn_frases.place(x=10, y=10)

# --- reconocimiento de voz en hilo ---
def escuchar():
    ruta_sonido_ok = os.path.join(ASSETS_DIR, "confirm1.wav")
    ruta_sonido_clip = os.path.join(ASSETS_DIR, "clip.wav")
    ruta_sonido_good = os.path.join(ASSETS_DIR, "ok.wav")
   
    # cargar modelo (igual)
    model = Model("model")

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                    input=True, frames_per_buffer=4000)
    stream.start_stream()
    print("Escuchando...")
    winsound.PlaySound(ruta_sonido_good, winsound.SND_FILENAME)

    primera_confirmacion = False
    tiempo_confirmacion = None

    # inicializar recognizer con frases actuales
    # NOTA: vamos a reconstruir rec si las frases cambian en caliente
    rec = None
    frases_previas = None

    while True:
        # intentar leer audio
        try:
            data = stream.read(4000, exception_on_overflow=False)
        except Exception:
            continue

        # recargar frases si cambiaron (permite editar en caliente)
        try:
            frases = cargar_frases()
        except Exception:
            frases = ["ok garmin", "video station"]
        # asegurar al menos 2
        if len(frases) < 2:
            frases = frases + [""] * (2 - len(frases))

        # si las frases cambiaron, reconstruir recognizer
        if frases != frases_previas:
            try:
                grammar = json.dumps(frases, ensure_ascii=False)
                rec = KaldiRecognizer(model, 16000, grammar)
                frases_previas = list(frases)
                print("Gramática actualizada:", grammar)
            except Exception as e:
                print("Error al crear KaldiRecognizer:", e)
                rec = KaldiRecognizer(model, 16000)  # fallback

        if rec is None:
            continue

        if rec.AcceptWaveform(data):
            try:
                result = json.loads(rec.Result())
            except Exception:
                continue
            texto = result.get("text", "").strip()
            if texto:
                print("Reconocido:", texto)

            palabra1 = frases[0].strip().lower()
            palabra2 = frases[1].strip().lower()

            if texto == palabra1:
                primera_confirmacion = True
                tiempo_confirmacion = time.time()
                if os.path.exists(ruta_sonido_ok):
                    winsound.PlaySound(ruta_sonido_ok, winsound.SND_FILENAME)

            elif primera_confirmacion and texto == palabra2:
                print("¡Clip guardado!")
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
            try:
                cfg_now = cargar_config()
                cooldown = float(cfg_now.get("cooldown", 5))
            except Exception:
                cooldown = 5.0
            if time.time() - tiempo_confirmacion > cooldown:
                print("Reiniciando confirmacion...")
                primera_confirmacion = False
                tiempo_confirmacion = None


# iniciar hilo de escucha
threading.Thread(target=escuchar, daemon=True).start()

root.mainloop()

