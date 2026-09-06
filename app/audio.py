# ~/Documentos/Projetos/baseus-presenter-linux/app/audio.py
import os
import json
import queue
import datetime
from urllib.error import URLError
from PyQt5.QtCore import QThread, pyqtSignal

from .logger import get_logger
log = get_logger(__name__)

import sounddevice as sd

try:
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1) 
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    log.warning("Vosk não encontrado. Transcrição desativada.")

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False
    log.warning("Argos Translate não encontrado. Tradução desativada.")

class ArgosIndexThread(QThread):
    finished = pyqtSignal(bool, str)
    def run(self):
        if not ARGOS_AVAILABLE:
            self.finished.emit(False, "Argos não instalado.")
            return
        try:
            argostranslate.package.update_package_index()
            self.finished.emit(True, "Índice atualizado.")
        except Exception as e:
            self.finished.emit(False, str(e))

class AudioThread(QThread):
    partial_ready = pyqtSignal(str)
    final_ready = pyqtSignal(str)
    audio_warning = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
        self.is_recording = False
        self.is_translating = False
        
        self.model = None
        self.recognizer = None
        self.q = queue.Queue()
        self._needs_reload = True 
        self.txt_path = None

    def set_recording(self, state):
        self.is_recording = state
        if state:
            if not self.model:
                self.audio_warning.emit("⚠️ IA de Voz ausente!")
                return
            
            pasta = self.config.get("save_dir", os.path.expanduser("~"))
            os.makedirs(pasta, exist_ok=True)
            nome_arquivo = datetime.datetime.now().strftime("Aula_%Y-%m-%d_%H-%M-%S.txt")
            self.txt_path = os.path.join(pasta, nome_arquivo)
            with open(self.txt_path, 'w', encoding='utf-8') as f:
                f.write(f"--- Transcrição Iniciada: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ---\n\n")
            
            # Avisa se está silencioso ou com legenda
            if self.config.get("show_subtitles", True):
                self.audio_warning.emit("🎙️ Gravação Iniciada (Com Legendas)!")
            else:
                self.audio_warning.emit("🎙️ Gravação Silenciosa Iniciada (Salvando no TXT)!")
        else:
            self.audio_warning.emit("⏸️ Gravação Pausada.")
            self.txt_path = None

    def set_translating(self, state):
        self.is_translating = state
        if state and not ARGOS_AVAILABLE:
            self.audio_warning.emit("⚠️ Argos Translate não instalado!")
        elif state:
            self.audio_warning.emit("🌐 Tradução Simultânea ON!")
        else:
            self.audio_warning.emit("🌐 Tradução Simultânea OFF.")

    def trigger_reload(self):
        self._needs_reload = True

    def _load_model(self):
        if not VOSK_AVAILABLE: return
        path = self.config["audio"].get("selected_model_path", "")
        if not path or not os.path.exists(path):
            self.model, self.recognizer = None, None
            return

        try:
            log.info(f"Carregando Vosk em background: {path}")
            self.model = Model(path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            log.info("✅ Vosk carregado com sucesso!")
        except Exception as e:
            log.error(f"Falha ao carregar Vosk: {e}")
            self.model, self.recognizer = None, None

    def _audio_callback(self, indata, frames, time, status):
        # AQUI FOI CORRIGIDO: O microfone abre se for para Gravar OU Traduzir
        if self.is_recording or self.is_translating:
            self.q.put(bytes(indata))

    def _get_device_id(self):
        saved = self.config["audio"].get("input_device")
        if saved is not None: return saved
        for idx, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0 and 'baseus' in dev['name'].lower():
                return idx
        return None

    def run(self):
        device_id = self._get_device_id()
        log.info(f"Usando microfone ID: {device_id if device_id else 'Padrão do Sistema'}")
        
        try:
            with sd.RawInputStream(samplerate=16000, blocksize=4000, device=device_id, 
                                   dtype='int16', channels=1, callback=self._audio_callback):
                while self.running:
                    if self._needs_reload:
                        self._load_model()
                        self._needs_reload = False

                    if not self.q.empty():
                        data = self.q.get()
                        if self.recognizer and (self.is_recording or self.is_translating):
                            if self.recognizer.AcceptWaveform(data):
                                res = json.loads(self.recognizer.Result())
                                text = res.get('text', '')
                                if text:
                                    final_text = self._translate_if_needed(text)
                                    
                                    # LÓGICA DE EXIBIÇÃO INTELIGENTE
                                    if self.config.get("show_subtitles", True) or self.is_translating:
                                        self.final_ready.emit(final_text)
                                        
                                    if self.txt_path and self.is_recording:
                                        with open(self.txt_path, 'a', encoding='utf-8') as f:
                                            f.write(final_text + "\n")
                            else:
                                res = json.loads(self.recognizer.PartialResult())
                                text = res.get('partial', '')
                                if text:
                                    if self.config.get("show_subtitles", True) or self.is_translating:
                                        self.partial_ready.emit(self._translate_if_needed(text))
                    else:
                        self.msleep(10)
        except Exception as e:
            log.error(f"Erro no SoundDevice: {e}")

    def _translate_if_needed(self, text):
        if self.is_translating and ARGOS_AVAILABLE and text:
            target_lang = self.config["audio"].get("target_lang", "en")
            try: 
                return argostranslate.translate.translate(text, "pt", target_lang)
            except Exception as e: 
                self.audio_warning.emit(f"⚠️ Erro de Tradução: Pacote pt->{target_lang} ausente!")
                log.warning(f"Erro Argos: {e}")
                return text
        return text
        
    def stop(self):
        self.running = False
        self.wait()
