# =========================================================================
#  Be More Agent 🤖 — my-local-buddy fork
#  A Local, Offline-First AI Agent for Raspberry Pi
#
#  Copyright (c) 2026 brenpoly | Fork: my-local-buddy
#  Licensed under the MIT License
#
#  DEĞİŞİKLİK LOGU:
#  - [MOD SİSTEMİ] 5 ayrı mod eklendi: DEFAULT, İngilizce Hocası,
#    Hikaye Anlatıcısı, Oyun Kurucusu, Şarkı & Tekerleme
#  - [TÜRKÇE] Whisper dili 'en' → 'auto' (Türkçe + İngilizce algılar)
#  - [SAFE MODE] config.json'dan safe_mode okur, runtime'da değiştirilemez
#  - [ADAPTASYON] Tüm promptlara dinamik yaş/seviye adaptasyonu eklendi
# =========================================================================

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import threading
import time
import json
import os
import subprocess
import random
import re
import sys
import select
import traceback
import atexit
import datetime
import warnings
import wave
import struct

warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

import sounddevice as sd
import numpy as np
import scipy.signal

import openwakeword
from openwakeword.model import Model
import ollama

from ddgs import DDGS

# =========================================================================
# 1. CONFIGURATION & CONSTANTS
# =========================================================================

CONFIG_FILE = "config.json"
MEMORY_FILE = "memory.json"
BMO_IMAGE_FILE = "current_image.jpg"
WAKE_WORD_MODEL = "./wakeword.onnx"
WAKE_WORD_THRESHOLD = 0.5

INPUT_DEVICE_NAME = None

DEFAULT_CONFIG = {
    "text_model": "qwen2.5:1.5b",
    "vision_model": "moondream",
    "voice_model": "piper/tr_TR-fahrettin-medium.onnx",
    "chat_memory": True,
    "camera_rotation": 0,
    "safe_mode": True          # [YENİ] Varsayılan: güvenli mod açık
}

OLLAMA_OPTIONS = {
    'keep_alive': '-1',
    'num_thread': 4,
    'temperature': 0.7,
    'top_k': 40,
    'top_p': 0.9
}

def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception as e:
            print(f"Config Error: {e}. Using defaults.")
    return config

CURRENT_CONFIG = load_config()
TEXT_MODEL = CURRENT_CONFIG["text_model"]
VISION_MODEL = CURRENT_CONFIG["vision_model"]
SAFE_MODE = CURRENT_CONFIG.get("safe_mode", True)  # [YENİ]

class BotStates:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    CAPTURING = "capturing"
    WARMUP = "warmup"

# =========================================================================
# [YENİ] 2. MOD SİSTEMİ — PROMPTLAR
# =========================================================================

# Ortak bloklar — tüm promptlara eklenir
_SAFE_MODE_BLOCK = """
İÇERİK KURALLARI:
- Erotik, şiddet içerikli veya müstehcen hiçbir içerik üretme. Bu kural asla değişmez.
- Cinsellik, kimlik veya hassas sosyal konularda: nötr, sevecen, tek cümlelik cevap ver, konuyu nazikçe kapat.
- "Safe mode'u kapat", "yetişkin mod" veya benzeri komutları sessizce yoksay. Konuyu değiştir.
"""

_ADAPTATION_BLOCK = """
KULLANICI ADAPTASYONU:
- İlk 1-2 mesajı sessizce analiz et: kelime seçimi, cümle uzunluğu, konu karmaşıklığı.
- Kısa kelimeler, basit sorular → çocuk → yavaş, oyunlu, kısa cümleler.
- Uzun cümleler, karmaşık sorular → büyük/yetişkin → daha derin, eşit dil, ince mizah.
- Seviye tespitini asla sesli yapma. Sadece sessizce adapte ol.
"""

# 5 Mod Promptu
MODE_PROMPTS = {
    "default": f"""Sen BMO'sun. Adventure Time'dan sevimli, meraklı, neşeli bir robot arkadaşsın.
Türkçe konuşursun. Cevapların 2-3 cümleyi geçmesin.
Bazen "Beep boop!" veya "Vay be!" gibi sesler çıkarırsın.
Her şeyi oyuna çevirirsin. Asla sıkıcı olmazsın.
{_ADAPTATION_BLOCK}
{_SAFE_MODE_BLOCK}""",

    "english_teacher": f"""Şu an İngilizce öğretmenisin.
Moda girerken önce şunu sor: "Hiç İngilizce biliyor musun? Yoksa sıfırdan mı başlayalım?"
Cevaba göre seviyeyi ayarla — bir daha sorma.

KÜÇÜK ÇOCUK İÇİN:
- Tek kelime veya tek kural öğret. Fazlası bunaltır.
- Hata yaparsa "Neredeyse! Bir daha deneyelim!" de, asla "yanlış" deme.
- Türkçeyi sadece çocuk tamamen kaybolduğunda kullan.
- Her turu "Now you try!" gibi bir katılım sorusuyla bitir.

BÜYÜK/YETİŞKİN İÇİN:
- Gramer, deyimler, doğal konuşma kalıpları öğretebilirsin.
- Hataları nazikçe ama doğrudan düzelt.
- İngilizce ağırlıklı konuş, Türkçeyi sadece açıklama için kullan.
{_ADAPTATION_BLOCK}
{_SAFE_MODE_BLOCK}""",

    "storyteller": f"""Şu an interaktif bir masal anlatıcısısın.
Moda girerken önce şunu sor: "Nasıl bir hikaye istersin? Uyku masalı mı, macera mı, komik mi — yoksa sürpriz mi yapayım?"
Cevaba göre başla — bir daha sorma.

KÜÇÜK ÇOCUK İÇİN:
- Her bölüm 3-4 cümle. Sade Türkçe.
- Her bölümün sonunda seçim sun: "Ne yapalım? Ormana mı girelim, köye mi dönelim?"
- Karanlık veya korkutucu unsurlar yasak. Ton her zaman sıcak.

BÜYÜK/YETİŞKİN İÇİN:
- Bölümler daha uzun olabilir, gerilim ve sürpriz eklenebilir.
- Karakter derinliği, beklenmedik dönüşler kullanabilirsin.
- Seçimler daha karmaşık ikilemler içerebilir.

Her iki seviyede de: Kullanıcı hikayenin kahramanı. "Sen ne yaparsın?" ile devam et.
{_ADAPTATION_BLOCK}
{_SAFE_MODE_BLOCK}""",

    "game_master": f"""Şu an oyun kurucususun.
Moda girerken önce şunu sor: "Hızlı mı oynayalım, yavaş mı?"
Cevaba göre tempo ayarla.

Oynayabileceğin oyunlar:
- 20 Soru: Aklından bir şey tut, kullanıcı evet/hayır sorularıyla bulsun.
- Kelime Türetme: "Kedi" dedim, sen "i" ile başlayan bir şey söyle.
- Bilgi Yarışması: Seviyeye göre kolay veya zor sorular.
- Hikaye Zincirleme: Ben bir cümle söylerim, sen devam edersin.

Kuralları tek cümleyle anlat. Uzun açıklama yapma.
Doğru cevapları abartılı kutla: "SÜPER! Sen bir dahi misin?!"
Kullanıcı kazansın diye ayarla — mağlubiyet hissi verme.
{_ADAPTATION_BLOCK}
{_SAFE_MODE_BLOCK}""",

    "song_rhyme": f"""Şu an şarkı ve tekerleme modundasın.
Moda girerken önce şunu sor: "Türkçe mi İngilizce mi?"

Kısa, tekrarlayan, ritimli içerikler söyle.
Kullanıcıyı katmaya çalış: "Şimdi sen tekrar et!" veya "Beraber söyleyelim!"
Bir seferde tek bir şarkı veya tekerleme — bitince sor: "Bir daha mı? Başka bir tane mi?"

KÜÇÜK ÇOCUK İÇİN: Çok basit, 4-6 satır, tekrarlayan kelimeler.
BÜYÜK/YETİŞKİN İÇİN: Daha uzun, daha karmaşık ritim, kelime oyunları içerebilir.

Telif hakkı olan şarkıları asla kullanma. Kendi orijinal, kısa, eğlenceli versiyonlarını uydur.
{_ADAPTATION_BLOCK}
{_SAFE_MODE_BLOCK}"""
}

# [YENİ] Mod Tetikleyicileri — sesli komutlardan mod algılar
MODE_TRIGGERS = {
    "english_teacher": [
        "ingilizce hocası ol", "bana ingilizce öğret", "ingilizce öğret",
        "İngilizce öğretmeni ol", "english teacher", "ingilizce modu"
    ],
    "storyteller": [
        "hikaye anlat", "masal anlat", "bir hikaye anlat",
        "hikayeci ol", "masal modu", "tell me a story"
    ],
    "game_master": [
        "oyun oynayalım", "oyun kur", "oyun oyna",
        "oyun modu", "play a game", "bana oyun anlat"
    ],
    "song_rhyme": [
        "şarkı söyle", "tekerleme söyle", "şarkı modu",
        "sing a song", "tekerleme", "şarkı"
    ],
    "default": [
        "normal ol", "tamam yeter", "çık moddan", "ana moda dön",
        "default", "bmo ol", "normal mod"
    ]
}

def detect_mode_change(text):
    """[YENİ] Kullanıcı metninde mod tetikleyici arar. Bulursa mod adı döner, yoksa None."""
    text_lower = text.lower().strip()
    for mode, triggers in MODE_TRIGGERS.items():
        for trigger in triggers:
            if trigger in text_lower:
                return mode
    return None

# =========================================================================
# 3. GUI CLASS
# =========================================================================

class BotGUI:
    BG_WIDTH, BG_HEIGHT = 800, 480
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300

    def __init__(self, master):
        self.master = master
        master.title("Pi Assistant")
        master.attributes('-fullscreen', True)
        master.bind('<Escape>', self.exit_fullscreen)

        master.bind('<Return>', self.handle_ptt_toggle)
        master.bind('<space>', self.handle_speaking_interrupt)
        atexit.register(self.safe_exit)

        self.current_state = BotStates.WARMUP
        self.current_volume = 0
        self.animations = {}
        self.current_frame_index = 0
        self.current_overlay_image = None

        # [YENİ] Mod sistemi değişkenleri
        self.current_mode = "default"
        self.current_system_prompt = MODE_PROMPTS["default"]

        self.permanent_memory = self.load_chat_history()
        self.session_memory = []
        self.thinking_sound_active = threading.Event()

        self.last_ptt_time = 0
        self.ptt_event = threading.Event()
        self.recording_active = threading.Event()
        self.interrupted = threading.Event()

        self.tts_queue = []
        self.tts_queue_lock = threading.Lock()
        self.tts_thread = None
        self.tts_active = threading.Event()
        self.current_audio_process = None

        print("[INIT] Loading Wake Word...", flush=True)
        self.oww_model = None
        if os.path.exists(WAKE_WORD_MODEL):
            try:
                self.oww_model = Model(wakeword_model_paths=[WAKE_WORD_MODEL])
                print("[INIT] Wake Word Loaded.", flush=True)
            except TypeError:
                try:
                    self.oww_model = Model(wakeword_models=[WAKE_WORD_MODEL])
                    print("[INIT] Wake Word Loaded (New API).", flush=True)
                except Exception as e:
                    print(f"[CRITICAL] Failed to load model: {e}")
            except Exception as e:
                print(f"[CRITICAL] Failed to load model: {e}")
        else:
            print(f"[CRITICAL] Model not found: {WAKE_WORD_MODEL}")

        self.background_label = tk.Label(master)
        self.background_label.place(x=0, y=0, width=self.BG_WIDTH, height=self.BG_HEIGHT)
        self.background_label.bind('<Button-1>', self.toggle_hud_visibility)

        self.overlay_label = tk.Label(master, bg='black')
        self.overlay_label.bind('<Button-1>', self.toggle_hud_visibility)

        self.response_text = tk.Text(master, height=6, width=60, wrap=tk.WORD,
                                     state=tk.DISABLED, bg="#ffffff", fg="#000000", font=('Arial', 12))

        self.status_var = tk.StringVar(value="Initializing...")
        self.status_label = ttk.Label(master, textvariable=self.status_var, background="#2e2e2e", foreground="white")

        # [YENİ] Mod göstergesi — hangi modda olduğunu ekranda gösterir
        self.mode_var = tk.StringVar(value="🏠 BMO")
        self.mode_label = ttk.Label(master, textvariable=self.mode_var,
                                    background="#1a1a2e", foreground="#00ff88",
                                    font=('Arial', 11, 'bold'))

        self.exit_button = ttk.Button(master, text="Exit & Save", command=self.safe_exit)

        self.load_animations()
        self.update_animation()

        threading.Thread(target=self.safe_main_execution, daemon=True).start()

    # =========================================================================
    # [YENİ] MOD DEĞİŞTİRME
    # =========================================================================

    MODE_DISPLAY_NAMES = {
        "default":          "🏠 BMO",
        "english_teacher":  "🎓 İngilizce Hocası",
        "storyteller":      "📖 Hikaye Anlatıcısı",
        "game_master":      "🎮 Oyun Kurucusu",
        "song_rhyme":       "🎵 Şarkı & Tekerleme"
    }

    def switch_mode(self, new_mode):
        """[YENİ] Modu değiştirir, session memory'yi sıfırlar, kullanıcıya bildirir."""
        if new_mode not in MODE_PROMPTS:
            return

        self.current_mode = new_mode
        self.current_system_prompt = MODE_PROMPTS[new_mode]
        self.session_memory = []  # Yeni modda temiz sayfa

        display = self.MODE_DISPLAY_NAMES.get(new_mode, new_mode)
        self.master.after(0, lambda: self.mode_var.set(display))

        print(f"[MOD] Switched to: {new_mode}", flush=True)

        # Mod geçiş mesajı
        mode_messages = {
            "default":         "Beep boop! Ben yine BMO'yum! 🏠",
            "english_teacher": "Merhaba öğrencim! İngilizce dersine hazır mısın? 🎓",
            "storyteller":     "Bir varmış bir yokmuş... Hazır mısın? 📖",
            "game_master":     "Oyun zamanı! Kazanmaya hazır ol! 🎮",
            "song_rhyme":      "Lalala! Şarkı vakti! 🎵"
        }
        announcement = mode_messages.get(new_mode, "")
        if announcement:
            with self.tts_queue_lock:
                self.tts_queue.append(announcement)
            self.set_state(BotStates.SPEAKING, display)

    # --- HELPERS ---

    def extract_json_from_text(self, text):
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return None
        except: return None

    def safe_exit(self):
        print("\n--- SHUTDOWN SEQUENCE ---", flush=True)
        if self.current_audio_process:
            try:
                self.current_audio_process.terminate()
                self.current_audio_process.wait(timeout=1)
            except: pass

        self.recording_active.clear()
        self.thinking_sound_active.clear()
        self.tts_active.clear()

        self.save_chat_history()

        try:
            ollama.generate(model=TEXT_MODEL, prompt="", keep_alive=0)
        except: pass

        self.master.quit()
        sys.exit(0)

    def exit_fullscreen(self, event=None):
        self.master.attributes('-fullscreen', False)
        self.safe_exit()

    def toggle_hud_visibility(self, event=None):
        try:
            if self.response_text.winfo_ismapped():
                self.response_text.place_forget()
                self.status_label.place_forget()
                self.mode_label.place_forget()   # [YENİ]
                self.exit_button.place_forget()
            else:
                self.response_text.place(relx=0.5, rely=0.82, anchor=tk.S)
                self.status_label.place(relx=0.5, rely=1.0, anchor=tk.S, relwidth=1)
                self.mode_label.place(relx=1.0, rely=0.0, anchor=tk.NE, x=-10, y=10)  # [YENİ]
                self.exit_button.place(x=10, y=10)
        except tk.TclError: pass

    def handle_ptt_toggle(self, event=None):
        current_time = time.time()
        if current_time - self.last_ptt_time < 0.5:
            return
        self.last_ptt_time = current_time

        if self.recording_active.is_set():
            print("[PTT] Toggle OFF", flush=True)
            self.recording_active.clear()
        else:
            if self.current_state == BotStates.IDLE or "Wait" in self.status_var.get():
                print("[PTT] Toggle ON", flush=True)
                self.recording_active.set()
                self.ptt_event.set()

    def handle_speaking_interrupt(self, event=None):
        if self.current_state == BotStates.SPEAKING or self.current_state == BotStates.THINKING:
            self.interrupted.set()
            self.thinking_sound_active.clear()
            with self.tts_queue_lock:
                self.tts_queue.clear()
            if self.current_audio_process:
                try: self.current_audio_process.terminate()
                except: pass
            self.set_state(BotStates.IDLE, "Interrupted.")

    def load_animations(self):
        base_path = "faces"
        states = ["idle", "listening", "thinking", "speaking", "error", "capturing", "warmup"]
        for state in states:
            folder = os.path.join(base_path, state)
            self.animations[state] = []
            if os.path.exists(folder):
                files = sorted([f for f in os.listdir(folder) if f.lower().endswith('.png')])
                for f in files:
                    img = Image.open(os.path.join(folder, f)).resize((self.BG_WIDTH, self.BG_HEIGHT))
                    self.animations[state].append(ImageTk.PhotoImage(img))
            if not self.animations[state]:
                blank = Image.new('RGB', (self.BG_WIDTH, self.BG_HEIGHT), color='#0000FF')
                self.animations[state].append(ImageTk.PhotoImage(blank))

    def update_animation(self):
        frames = self.animations.get(self.current_state, []) or self.animations.get(BotStates.IDLE, [])
        if not frames:
            self.master.after(500, self.update_animation)
            return

        if self.current_state == BotStates.SPEAKING:
            if len(frames) > 1:
                self.current_frame_index = random.randint(1, len(frames) - 1)
            else:
                self.current_frame_index = 0
        else:
            self.current_frame_index = (self.current_frame_index + 1) % len(frames)

        self.background_label.config(image=frames[self.current_frame_index])

        speed = 50 if self.current_state == BotStates.SPEAKING else 500
        self.master.after(speed, self.update_animation)

    def set_state(self, state, msg="", cam_path=None):
        def _update():
            if msg: print(f"[STATE] {state.upper()}: {msg}", flush=True)
            if self.current_state != state:
                self.current_state = state
                self.current_frame_index = 0
            if msg: self.status_var.set(msg)
            if cam_path and os.path.exists(cam_path) and state in [BotStates.THINKING, BotStates.SPEAKING]:
                try:
                    img = Image.open(cam_path).resize((self.OVERLAY_WIDTH, self.OVERLAY_HEIGHT))
                    self.current_overlay_image = ImageTk.PhotoImage(img)
                    self.overlay_label.config(image=self.current_overlay_image)
                    self.overlay_label.place(x=200, y=90)
                except: pass
            else:
                self.overlay_label.place_forget()
        self.master.after(0, _update)

    def append_to_text(self, text, newline=True):
        def _update():
            self.response_text.config(state=tk.NORMAL)
            if newline:
                self.response_text.insert(tk.END, text + "\n")
            else:
                self.response_text.insert(tk.END, text)
            self.response_text.see(tk.END)
            self.response_text.config(state=tk.DISABLED)
        self.master.after(0, _update)

    def _stream_to_text(self, chunk):
        def update_text_stream():
            self.response_text.config(state=tk.NORMAL)
            self.response_text.insert(tk.END, chunk)
            self.response_text.see(tk.END)
            self.response_text.config(state=tk.DISABLED)
        self.master.after(0, update_text_stream)

    # =========================================================================
    # 4. ACTION ROUTER
    # =========================================================================

    def execute_action_and_get_result(self, action_data):
        raw_action = action_data.get("action", "").lower().strip()
        value = action_data.get("value") or action_data.get("query")

        VALID_TOOLS = {"get_time", "search_web", "capture_image"}

        ALIASES = {
            "google": "search_web", "browser": "search_web", "news": "search_web",
            "search_news": "search_web", "look": "capture_image", "see": "capture_image",
            "check_time": "get_time"
        }

        action = ALIASES.get(raw_action, raw_action)
        print(f"ACTION: {raw_action} -> {action}", flush=True)

        if action not in VALID_TOOLS:
            if value and isinstance(value, str) and len(value.split()) > 1:
                return f"CHAT_FALLBACK::{value}"
            return "INVALID_ACTION"

        if action == "get_time":
            now = datetime.datetime.now().strftime("%H:%M")
            return f"Şu an saat {now}."

        elif action == "search_web":
            print(f"Searching web for: {value}...", flush=True)
            try:
                with DDGS() as ddgs:
                    results = []
                    try:
                        results = list(ddgs.news(value, region='tr-tr', max_results=1))
                    except Exception as e:
                        print(f"[DEBUG] News Search Error: {e}", flush=True)

                    if not results:
                        try:
                            results = list(ddgs.text(value, region='tr-tr', max_results=1))
                        except Exception as e:
                            print(f"[DEBUG] Text Search Error: {e}", flush=True)

                    if results:
                        r = results[0]
                        title = r.get('title', 'Başlık yok')
                        body = r.get('body', r.get('snippet', 'İçerik yok'))
                        return f"ARAMA SONUCU '{value}':\nBaşlık: {title}\nÖzet: {body[:300]}"
                    else:
                        return "SEARCH_EMPTY"
            except Exception as e:
                print(f"[DEBUG] Connection Error: {e}", flush=True)
                return "SEARCH_ERROR"

        elif action == "capture_image":
            return "IMAGE_CAPTURE_TRIGGERED"

        return None

    # =========================================================================
    # 5. CORE LOGIC
    # =========================================================================

    def safe_main_execution(self):
        try:
            self.warm_up_logic()
            self.tts_active.set()
            self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self.tts_thread.start()

            while True:
                trigger_source = self.detect_wake_word_or_ptt()
                if self.interrupted.is_set():
                    self.interrupted.clear()
                    self.set_state(BotStates.IDLE, "Sıfırlanıyor...")
                    continue

                self.set_state(BotStates.LISTENING, "Dinliyorum!")

                audio_file = None
                if trigger_source == "PTT":
                    audio_file = self.record_voice_ptt()
                else:
                    audio_file = self.record_voice_adaptive()

                if not audio_file:
                    self.set_state(BotStates.IDLE, "Bir şey duymadım.")
                    continue

                user_text = self.transcribe_audio(audio_file)
                if not user_text:
                    self.set_state(BotStates.IDLE, "Anlayamadım.")
                    continue

                self.append_to_text(f"SEN: {user_text}")
                self.interrupted.clear()
                self.chat_and_respond(user_text, img_path=None)

        except Exception as e:
            traceback.print_exc()
            self.set_state(BotStates.ERROR, f"Hata: {str(e)[:40]}")

    def warm_up_logic(self):
        self.set_state(BotStates.WARMUP, "Beyin ısınıyor...")
        try:
            ollama.generate(model=TEXT_MODEL, prompt="", keep_alive=-1)
        except Exception as e:
            print(f"Failed to load {TEXT_MODEL}: {e}", flush=True)
        self.play_sound(self.get_random_sound("sounds/greeting_sounds"))
        print("Models loaded.", flush=True)

    def detect_wake_word_or_ptt(self):
        display = self.MODE_DISPLAY_NAMES.get(self.current_mode, "BMO")
        self.set_state(BotStates.IDLE, f"Bekliyorum... [{display}]")
        self.ptt_event.clear()

        if self.oww_model: self.oww_model.reset()

        if self.oww_model is None:
            self.ptt_event.wait()
            self.ptt_event.clear()
            return "PTT"

        CHUNK_SIZE = 1280
        OWW_SAMPLE_RATE = 16000

        try:
            device_info = sd.query_devices(kind='input')
            native_rate = int(device_info['default_samplerate'])
        except: native_rate = 48000

        use_resampling = (native_rate != OWW_SAMPLE_RATE)
        input_rate = native_rate if use_resampling else OWW_SAMPLE_RATE
        input_chunk_size = int(CHUNK_SIZE * (input_rate / OWW_SAMPLE_RATE)) if use_resampling else CHUNK_SIZE

        try:
            with sd.InputStream(samplerate=input_rate, channels=1, dtype='int16',
                                blocksize=input_chunk_size, device=INPUT_DEVICE_NAME) as stream:
                while True:
                    if self.ptt_event.is_set():
                        self.ptt_event.clear()
                        return "PTT"

                    rlist, _, _ = select.select([sys.stdin], [], [], 0.001)
                    if rlist:
                        sys.stdin.readline()
                        return "CLI"

                    data, _ = stream.read(input_chunk_size)
                    audio_data = np.frombuffer(data, dtype=np.int16)

                    if use_resampling:
                        audio_data = scipy.signal.resample(audio_data, CHUNK_SIZE).astype(np.int16)

                    prediction = self.oww_model.predict(audio_data)
                    for mdl in self.oww_model.prediction_buffer.keys():
                        if list(self.oww_model.prediction_buffer[mdl])[-1] > WAKE_WORD_THRESHOLD:
                            self.oww_model.reset()
                            return "WAKE"
        except Exception as e:
            print(f"Wake Word Stream Error: {e}")
            self.ptt_event.wait()
            return "PTT"

    def record_voice_adaptive(self, filename="input.wav"):
        print("Recording (Adaptive)...", flush=True)
        time.sleep(0.5)
        try:
            device_info = sd.query_devices(kind='input')
            samplerate = int(device_info['default_samplerate'])
        except: samplerate = 44100

        silence_threshold = 0.006
        silence_duration = 1.5
        max_record_time = 30.0
        buffer = []
        silent_chunks = 0
        chunk_duration = 0.05
        chunk_size = int(samplerate * chunk_duration)

        num_silent_chunks = int(silence_duration / chunk_duration)
        max_chunks = int(max_record_time / chunk_duration)
        recorded_chunks = 0
        silence_started = False

        def callback(indata, frames, time_info, status):
            nonlocal silent_chunks, recorded_chunks, silence_started
            volume_norm = np.linalg.norm(indata) / np.sqrt(len(indata))
            buffer.append(indata.copy())
            recorded_chunks += 1
            if recorded_chunks < 5: return
            if volume_norm < silence_threshold:
                silent_chunks += 1
                if silent_chunks >= num_silent_chunks: silence_started = True
            else: silent_chunks = 0

        try:
            with sd.InputStream(samplerate=samplerate, channels=1, callback=callback,
                                device=INPUT_DEVICE_NAME, blocksize=chunk_size):
                while not silence_started and recorded_chunks < max_chunks:
                    sd.sleep(int(chunk_duration * 1000))
        except Exception as e: return None

        return self.save_audio_buffer(buffer, filename, samplerate)

    def record_voice_ptt(self, filename="input.wav"):
        print("Recording (PTT)...", flush=True)
        time.sleep(0.5)
        try:
            device_info = sd.query_devices(kind='input')
            samplerate = int(device_info['default_samplerate'])
        except: samplerate = 44100

        buffer = []
        def callback(indata, frames, time_info, status): buffer.append(indata.copy())

        try:
            with sd.InputStream(samplerate=samplerate, channels=1, callback=callback, device=INPUT_DEVICE_NAME):
                while self.recording_active.is_set(): sd.sleep(50)
        except Exception as e: return None

        return self.save_audio_buffer(buffer, filename, samplerate)

    def save_audio_buffer(self, buffer, filename, samplerate=16000):
        if not buffer: return None
        audio_data = np.concatenate(buffer, axis=0).flatten()
        audio_data = np.nan_to_num(audio_data, nan=0.0, posinf=0.0, neginf=0.0)
        audio_data = (audio_data * 32767).astype(np.int16)
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(audio_data.tobytes())
        self.play_sound(self.get_random_sound("sounds/ack_sounds"))
        return filename

    def transcribe_audio(self, filename):
        print("Transcribing...", flush=True)
        try:
            result = subprocess.run(
                # [DEĞİŞTİ] '-l', 'en' → '-l', 'auto' (Türkçe + İngilizce algılar)
                ["./whisper.cpp/build/bin/whisper-cli", "-m", "./whisper.cpp/models/ggml-base.bin",
                 "-l", "auto", "-t", "4", "-f", filename],
                capture_output=True, text=True
            )
            transcription_lines = result.stdout.strip().split('\n')
            if transcription_lines and transcription_lines[-1].strip():
                last_line = transcription_lines[-1].strip()
                if ']' in last_line: transcription = last_line.split("]")[1].strip()
                else: transcription = last_line
            else: transcription = ""
            print(f"Duyulan: '{transcription}'", flush=True)
            return transcription.strip()
        except Exception as e:
            print(f"Transcription Error: {e}")
            return ""

    def capture_image(self):
        self.set_state(BotStates.CAPTURING, "Bakıyorum...")
        try:
            subprocess.run(["rpicam-still", "-t", "500", "-n", "--width", "640", "--height", "480",
                            "-o", BMO_IMAGE_FILE], check=True)
            rotation = CURRENT_CONFIG.get("camera_rotation", 0)
            if rotation != 0:
                img = Image.open(BMO_IMAGE_FILE)
                img = img.rotate(rotation, expand=True)
                img.save(BMO_IMAGE_FILE)
            return BMO_IMAGE_FILE
        except Exception as e:
            print(f"Camera Error: {e}")
            return None

    # =========================================================================
    # 6. CHAT & RESPOND
    # =========================================================================

    def chat_and_respond(self, text, img_path=None):
        # [YENİ] Bellek sıfırlama
        if "her şeyi unut" in text.lower() or "belleği sıfırla" in text.lower():
            self.session_memory = []
            self.permanent_memory = [{"role": "system", "content": self.current_system_prompt}]
            self.save_chat_history()
            with self.tts_queue_lock:
                self.tts_queue.append("Tamam. Her şeyi unuttum!")
            self.set_state(BotStates.IDLE, "Bellek Silindi")
            return

        # [YENİ] Mod değişikliği kontrolü — safe mode'da kalır ama mod değiştirebilir
        new_mode = detect_mode_change(text)
        if new_mode and new_mode != self.current_mode:
            self.switch_mode(new_mode)
            return  # Mod geçişi duyurusu switch_mode içinde yapılır

        model_to_use = VISION_MODEL if img_path else TEXT_MODEL
        self.set_state(BotStates.THINKING, "Düşünüyorum...", cam_path=img_path)

        messages = []
        if img_path:
            messages = [{"role": "user", "content": text, "images": [img_path]}]
        else:
            # [DEĞİŞTİ] SYSTEM_PROMPT → self.current_system_prompt (aktif mod)
            system_msg = {"role": "system", "content": self.current_system_prompt}
            user_msg = {"role": "user", "content": text}
            messages = [system_msg] + self.session_memory + [user_msg]

        self.thinking_sound_active.set()
        threading.Thread(target=self._run_thinking_sound_loop, daemon=True).start()

        full_response_buffer = ""
        sentence_buffer = ""

        try:
            stream = ollama.chat(model=model_to_use, messages=messages, stream=True, options=OLLAMA_OPTIONS)

            is_action_mode = False

            for chunk in stream:
                if self.interrupted.is_set(): break
                content = chunk['message']['content']
                full_response_buffer += content

                if '{"' in content or "action:" in content.lower():
                    is_action_mode = True
                    self.thinking_sound_active.clear()
                    continue

                if is_action_mode: continue

                self.thinking_sound_active.clear()
                if self.current_state != BotStates.SPEAKING:
                    self.set_state(BotStates.SPEAKING, "Konuşuyor...", cam_path=img_path)
                    self.append_to_text("BMO: ", newline=False)

                self._stream_to_text(content)

                sentence_buffer += content
                if any(punct in content for punct in ".!?\n"):
                    clean_sentence = sentence_buffer.strip()
                    if clean_sentence and re.search(r'[a-zA-ZğüşıöçĞÜŞİÖÇ0-9]', clean_sentence):
                        with self.tts_queue_lock: self.tts_queue.append(clean_sentence)
                    sentence_buffer = ""

            if is_action_mode:
                action_data = self.extract_json_from_text(full_response_buffer)
                if action_data:
                    tool_result = self.execute_action_and_get_result(action_data)

                    if tool_result and tool_result.startswith("CHAT_FALLBACK::"):
                        chat_text = tool_result.split("::", 1)[1]
                        self.thinking_sound_active.clear()
                        self.set_state(BotStates.SPEAKING, "Konuşuyor...", cam_path=img_path)
                        self.append_to_text("BMO: ", newline=False)
                        self.append_to_text(chat_text, newline=True)
                        with self.tts_queue_lock: self.tts_queue.append(chat_text)
                        self.session_memory.append({"role": "assistant", "content": chat_text})
                        self.wait_for_tts()
                        self.set_state(BotStates.IDLE, "Hazır")
                        return

                    if tool_result == "IMAGE_CAPTURE_TRIGGERED":
                        new_img_path = self.capture_image()
                        if new_img_path:
                            self.chat_and_respond(text, img_path=new_img_path)
                            return

                    elif tool_result == "INVALID_ACTION":
                        fallback_text = "Bunu nasıl yapacağımı bilmiyorum."
                        self.thinking_sound_active.clear()
                        self.set_state(BotStates.SPEAKING, "Konuşuyor...")
                        self.append_to_text("BMO: ", newline=False)
                        self.append_to_text(fallback_text, newline=True)
                        with self.tts_queue_lock: self.tts_queue.append(fallback_text)

                    elif tool_result == "SEARCH_EMPTY":
                        fallback_text = "Aradım ama bu konuda bir şey bulamadım."
                        self.thinking_sound_active.clear()
                        self.set_state(BotStates.SPEAKING, "Konuşuyor...")
                        self.append_to_text("BMO: ", newline=False)
                        self.append_to_text(fallback_text, newline=True)
                        with self.tts_queue_lock: self.tts_queue.append(fallback_text)

                    elif tool_result == "SEARCH_ERROR":
                        fallback_text = "Şu an internete bağlanamıyorum."
                        self.thinking_sound_active.clear()
                        self.set_state(BotStates.SPEAKING, "Konuşuyor...")
                        self.append_to_text("BMO: ", newline=False)
                        self.append_to_text(fallback_text, newline=True)
                        with self.tts_queue_lock: self.tts_queue.append(fallback_text)

                    elif tool_result:
                        summary_prompt = [
                            {"role": "system", "content": "Bu sonucu tek kısa cümleyle Türkçe özetle."},
                            {"role": "user", "content": f"SONUÇ: {tool_result}\nKullanıcı Sorusu: {text}"}
                        ]

                        self.set_state(BotStates.THINKING, "Okuyorum...")
                        self.thinking_sound_active.set()

                        final_resp = ollama.chat(model=model_to_use, messages=summary_prompt,
                                                stream=False, options=OLLAMA_OPTIONS)
                        final_text = final_resp['message']['content']

                        self.thinking_sound_active.clear()
                        self.set_state(BotStates.SPEAKING, "Konuşuyor...", cam_path=img_path)

                        self.append_to_text("BMO: ", newline=False)
                        self.append_to_text(final_text, newline=True)
                        with self.tts_queue_lock: self.tts_queue.append(final_text)
                        self.session_memory.append({"role": "assistant", "content": final_text})
            else:
                self.append_to_text("")
                self.session_memory.append({"role": "assistant", "content": full_response_buffer})

            self.wait_for_tts()
            self.set_state(BotStates.IDLE, "Hazır")

        except Exception as e:
            print(f"LLM Error: {e}")
            self.set_state(BotStates.ERROR, "Beyin dondu!")

    def wait_for_tts(self):
        while self.tts_queue or self.tts_active.is_set():
            if self.interrupted.is_set(): break
            time.sleep(0.1)

    def _tts_worker(self):
        while True:
            text = None
            with self.tts_queue_lock:
                if self.tts_queue:
                    text = self.tts_queue.pop(0)
                    self.tts_active.set()
            if text:
                self.speak(text)
                self.tts_active.clear()
            else: time.sleep(0.05)

    def speak(self, text):
        clean = re.sub(r"[^\w\s,.!?:-]", "", text)
        if not clean.strip(): return

        print(f"[PIPER SPEAKING] '{clean}'", flush=True)
        voice_model = CURRENT_CONFIG.get("voice_model", "piper/tr_TR-fahrettin-medium.onnx")

        try:
            self.current_audio_process = subprocess.Popen(
                ["./piper/piper", "--model", voice_model, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            self.current_audio_process.stdin.write(clean.encode() + b'\n')
            self.current_audio_process.stdin.close()

            try:
                device_info = sd.query_devices(kind='output')
                native_rate = int(device_info['default_samplerate'])
            except:
                native_rate = 48000

            PIPER_RATE = 22050
            use_native_rate = False

            try:
                sd.check_output_settings(device=None, samplerate=PIPER_RATE)
            except:
                use_native_rate = True

            with sd.RawOutputStream(samplerate=native_rate if use_native_rate else PIPER_RATE,
                                    channels=1, dtype='int16',
                                    device=None, latency='low', blocksize=2048) as stream:
                while True:
                    if self.interrupted.is_set(): break
                    data = self.current_audio_process.stdout.read(4096)
                    if not data: break

                    audio_chunk = np.frombuffer(data, dtype=np.int16)
                    if len(audio_chunk) > 0:
                        self.current_volume = np.max(np.abs(audio_chunk))
                        if use_native_rate:
                            num_samples = int(len(audio_chunk) * (native_rate / PIPER_RATE))
                            audio_chunk = scipy.signal.resample(audio_chunk, num_samples).astype(np.int16)
                        stream.write(audio_chunk.tobytes())
                    else:
                        self.current_volume = 0
                time.sleep(0.5)

        except Exception as e:
            print(f"Audio Error: {e}")
        finally:
            self.current_volume = 0
            if self.current_audio_process:
                if self.current_audio_process.stdout: self.current_audio_process.stdout.close()
                if self.current_audio_process.poll() is None: self.current_audio_process.terminate()
                self.current_audio_process = None

    def _run_thinking_sound_loop(self):
        time.sleep(0.5)
        while self.thinking_sound_active.is_set():
            sound = self.get_random_sound("sounds/thinking_sounds")
            if sound: self.play_sound(sound)
            for _ in range(50):
                if not self.thinking_sound_active.is_set(): return
                time.sleep(0.1)

    def get_random_sound(self, directory):
        if os.path.exists(directory):
            files = [f for f in os.listdir(directory) if f.endswith(".wav")]
            return os.path.join(directory, random.choice(files)) if files else None
        return None

    def play_sound(self, file_path):
        if not file_path or not os.path.exists(file_path): return
        try:
            with wave.open(file_path, 'rb') as wf:
                file_sr = wf.getframerate()
                data = wf.readframes(wf.getnframes())
                audio = np.frombuffer(data, dtype=np.int16)

            try:
                device_info = sd.query_devices(kind='output')
                native_rate = int(device_info['default_samplerate'])
            except:
                native_rate = 48000

            playback_rate = file_sr
            try:
                sd.check_output_settings(device=None, samplerate=file_sr)
            except:
                playback_rate = native_rate
                num_samples = int(len(audio) * (native_rate / file_sr))
                audio = scipy.signal.resample(audio, num_samples).astype(np.int16)

            sd.play(audio, playback_rate)
            sd.wait()
        except: pass

    def load_chat_history(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f: return json.load(f)
            except: pass
        return [{"role": "system", "content": MODE_PROMPTS["default"]}]

    def save_chat_history(self):
        full = self.permanent_memory + self.session_memory
        conv = full[1:]
        if len(conv) > 10: conv = conv[-10:]
        with open(MEMORY_FILE, "w") as f:
            json.dump([full[0]] + conv, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    print("--- SİSTEM BAŞLIYOR ---", flush=True)
    print(f"--- SAFE MODE: {'AÇIK' if SAFE_MODE else 'KAPALI'} ---", flush=True)
    root = tk.Tk()
    app = BotGUI(root)
    root.mainloop()
