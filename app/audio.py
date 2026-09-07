# ~/Documentos/Projetos/baseus-presenter-linux/app/audio.py
import os
import json
import queue
import time
import array
import datetime
import threading
from urllib.error import URLError
from PyQt5.QtCore import QThread, pyqtSignal

from .logger import get_logger
from .config import Config, audio_cfg
log = get_logger(__name__)

import sounddevice as sd

# #18: limite da fila de blocos de áudio. Sem isso, se o reconhecedor/
# tradução ficar mais lento que a captura (comum ao traduzir PARCIAIS a
# cada quadro), a Queue() crescia sem limite — memória e atraso de legenda
# ilimitados. Cada bloco tem blocksize=4000 amostras int16 (~8KB); 200
# blocos ~= 1.6MB, uma folga generosa sem deixar a fila crescer para sempre.
AUDIO_QUEUE_MAXSIZE = 200

# Intervalo mínimo entre logs de fila saturada, para não inundar o arquivo
# de log quando o consumidor fica lento por um período prolongado.
_QUEUE_OVERFLOW_LOG_INTERVAL_S = 5.0

# #16: intervalo de espera antes de tentar reabrir o stream de áudio após
# uma falha (ex.: microfone desconectado). Evita busy-loop de reconexão.
_STREAM_RETRY_DELAY_S = 2.0

# --- Monitor de nível de entrada -------------------------------------------
# Diagnóstico de FALHA SILENCIOSA: o stream abre sem erro, os blocos chegam,
# mas são silêncio digital (ex.: microfone mudo no hardware, device errado,
# canal sem sinal). Antes disso o app simplesmente não transcrevia nada e o
# usuário não tinha como saber o motivo — só "não funciona".
#
# Referência medida no hardware real (tools/diagnose_audio.py): fala normal
# no microfone do passador dá RMS ~2000-7000; silêncio dá 0.0.
_LEVEL_SILENCE_RMS = 30.0      # abaixo disso: praticamente silêncio digital
_LEVEL_CHECK_WINDOW_S = 4.0    # janela para decidir se está mudo
_LEVEL_SUBSAMPLE = 16          # 1 a cada N amostras (custo desprizível)


def _rms_int16(data, step=_LEVEL_SUBSAMPLE):
    """
    RMS aproximado de um bloco PCM int16, usando só a biblioteca padrão.

    Sub-amostra para manter o custo irrelevante: a 4 blocos/s, isso são ~250
    operações por bloco em vez de 4000. Precisão mais que suficiente para
    distinguir "silêncio" de "fala".
    """
    amostras = array.array('h')
    amostras.frombytes(data)
    if not amostras:
        return 0.0
    total = 0
    n = 0
    for i in range(0, len(amostras), step):
        v = amostras[i]
        total += v * v
        n += 1
    return (total / n) ** 0.5 if n else 0.0

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

class AudioThread(QThread):
    partial_ready = pyqtSignal(str)
    final_ready = pyqtSignal(str)
    audio_warning = pyqtSignal(str)
    # #15: sinal dedicado para falhas que exigem que a UI sincronize o
    # estado (ex.: desmarcar o botão de gravação). audio_warning continua
    # existindo para avisos "soft" (ligou/desligou tradução, etc.);
    # audio_error é para falhas que INTERROMPEM a captura ou a escrita.
    audio_error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        # Aceita tanto o wrapper Config (com lock) quanto um dict cru, para
        # não quebrar chamadas antigas/testes.
        self.config = config if isinstance(config, Config) else Config(config)
        self.running = True
        self.is_recording = False
        self.is_translating = False
        
        self.model = None
        self.recognizer = None
        # #18: fila com limite. put_nowait() é usado no callback; quando
        # cheia, descartamos o bloco MAIS ANTIGO para abrir espaço — perder
        # um bloco antigo de ~250ms é preferível a crescer sem limite ou a
        # bloquear o callback do PortAudio (que roda em thread de tempo real).
        self.q = queue.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
        self._last_queue_overflow_log = 0.0

        # #17: contador de versão em vez de flag booleana. trigger_reload()
        # incrementa _reload_version; o loop compara com
        # _loaded_reload_version e só marca como "carregado" a versão que
        # efetivamente carregou. Antes, um _needs_reload=True que chegasse
        # DURANTE um _load_model() em andamento era apagado pelo
        # `self._needs_reload = False` do carregamento antigo, perdendo o
        # pedido de recarga mais recente (ex.: trocar de modelo duas vezes
        # rápido, ou trocar de perfil enquanto o modelo anterior carrega).
        self._reload_lock = threading.Lock()
        self._reload_version = 1
        self._loaded_reload_version = 0

        self.txt_path = None
        self._txt_lock = threading.Lock()  # Protege acesso concorrente a txt_path

        # #7/#8: quando a gravação é pausada/reiniciada, ainda pode haver
        # áudio pendente no reconhecedor que nunca chegou a um resultado
        # final. _pending_finalize sinaliza para a THREAD DE ÁUDIO (nunca a
        # GUI, que roda em outra thread e não pode tocar no KaldiRecognizer
        # com segurança) que deve drenar a fila, chamar FinalResult() e
        # escrever o resultado no ARQUIVO DA SESSÃO QUE ESTAVA ATIVA quando
        # a pausa foi solicitada — mesmo que uma nova sessão já tenha
        # comecado enquanto isso.
        self._pending_finalize = False
        self._finalize_ctx = None  # snapshot (txt_path, show_subtitles) da sessao pausada

        # #16: quando o microfone selecionado muda (troca manual ou troca de
        # perfil), a GUI chama request_stream_restart(). O stream em uso
        # (device_id fixo, capturado uma única vez antes do loop) precisa
        # ser fechado e reaberto com o novo device_id — sem isso a troca de
        # microfone na tela não tinha efeito nenhum até reiniciar o app.
        self._stream_restart_requested = False

        # Monitor de nível: detecta "gravando, mas sem sinal chegando".
        self._level_window_start = 0.0
        self._level_peak = 0.0
        self._level_warned = False

    def set_recording(self, state):
        """
        #14: is_recording so vira True DEPOIS de validar modelo e destino.
        Antes, `self.is_recording = state` era a PRIMEIRA linha da funcao —
        se o modelo estivesse ausente ou a criacao do arquivo falhasse, o
        estado ficava True mesmo sem nenhuma saida valida (a UI mostrava
        "gravando" indefinidamente).
        """
        if state:
            if not self.model:
                self.audio_warning.emit("⚠️ IA de Voz ausente!")
                return  # is_recording permanece no valor anterior (False)

            pasta = self.config.get("save_dir", os.path.expanduser("~"))
            try:
                os.makedirs(pasta, exist_ok=True)
                nome_arquivo = datetime.datetime.now().strftime("Aula_%Y-%m-%d_%H-%M-%S.txt")
                txt_path = os.path.join(pasta, nome_arquivo)
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"--- Transcrição Iniciada: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ---\n\n")
            except OSError as exc:
                # Pasta sem permissao / disco cheio: avisa em vez de deixar
                # o estado "ativo" sem nenhum arquivo de saida por baixo.
                log.exception(f"Não foi possível criar o arquivo de transcrição: {exc}")
                self.audio_warning.emit("⚠️ Falha ao criar o arquivo da aula!")
                return  # is_recording permanece False; nada foi validado ainda

            # So agora, com modelo E arquivo confirmados, ativa o estado.
            self.is_recording = True
            self._reset_level_monitor()  # começa a vigiar se chega áudio
            with self._txt_lock:
                self.txt_path = txt_path

            # Avisa se está silencioso ou com legenda
            if self.config.get_audio("show_subtitles", True):
                self.audio_warning.emit("🎙️ Gravação Iniciada (Com Legendas)!")
            else:
                self.audio_warning.emit("🎙️ Gravação Silenciosa Iniciada (Salvando no TXT)!")
        else:
            # #7: pausar nao pode simplesmente descartar o txt_path — pode
            # haver uma fala em andamento que o Vosk ainda nao fechou (nao
            # detectou silencio suficiente para AcceptWaveform retornar
            # True). Isso pede a THREAD DE AUDIO para drenar a fila e
            # chamar FinalResult() antes de soltar o destino desta sessao.
            with self._txt_lock:
                sessao_valida = bool(self.is_recording and self.txt_path)
                if sessao_valida:
                    self._finalize_ctx = {
                        "txt_path": self.txt_path,
                        "show_subtitles": self.config.get_audio("show_subtitles", True),
                    }
                    self._pending_finalize = True
                self.txt_path = None
            self.is_recording = False
            self.audio_warning.emit("⏸️ Gravação Pausada.")

    def set_translating(self, state):
        self.is_translating = state
        if state and not ARGOS_AVAILABLE:
            self.audio_warning.emit("⚠️ Argos Translate não instalado!")
        elif state:
            self.audio_warning.emit("🌐 Tradução Simultânea ON!")
        else:
            self.audio_warning.emit("🌐 Tradução Simultânea OFF.")

    def trigger_reload(self):
        """
        #17: apenas incrementa a versão pedida. O loop em run() é quem decide
        quando recarregar, comparando com a última versão efetivamente
        carregada — nunca perde um pedido por causa de uma recarga antiga
        que estava em andamento.
        """
        with self._reload_lock:
            self._reload_version += 1

    def request_stream_restart(self):
        """
        #16: pede para o loop de run() fechar o RawInputStream atual e abrir
        um novo com o device_id mais recente do config. Chamado pela GUI
        quando o usuário troca o microfone ou troca de perfil (perfis podem
        ter microfones diferentes).
        """
        self._stream_restart_requested = True

    def _load_model(self):
        if not VOSK_AVAILABLE: return
        path = self.config.get_audio("selected_model_path", "")
        if not path or not os.path.exists(path):
            self.model, self.recognizer = None, None
            return

        try:
            log.info(f"Carregando Vosk em background: {path}")
            self.model = Model(path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            log.info("✅ Vosk carregado com sucesso!")
        except Exception as e:
            log.exception(f"Falha ao carregar Vosk: {e}")
            self.model, self.recognizer = None, None
            self.audio_warning.emit("⚠️ Falha ao carregar o modelo de voz!")

    def _log_queue_overflow(self):
        """Log com throttling para não inundar o arquivo quando a fila enche."""
        now = time.monotonic()
        if now - self._last_queue_overflow_log >= _QUEUE_OVERFLOW_LOG_INTERVAL_S:
            self._last_queue_overflow_log = now
            log.warning(
                f"Fila de áudio saturada (maxsize={AUDIO_QUEUE_MAXSIZE}); "
                "descartando blocos mais antigos. O reconhecedor/tradução "
                "pode estar mais lento que a captura."
            )

    def _audio_callback(self, indata, frames, time_info, status):
        # AQUI FOI CORRIGIDO: O microfone abre se for para Gravar OU Traduzir
        if not (self.is_recording or self.is_translating or self._pending_finalize):
            return

        chunk = bytes(indata)
        try:
            self.q.put_nowait(chunk)
        except queue.Full:
            # #18: fila cheia — descarta o bloco MAIS ANTIGO para abrir
            # espaço para o mais recente. Isso roda no callback do
            # PortAudio (thread de tempo real): nunca pode bloquear aqui,
            # por isso put_nowait/get_nowait em vez de put()/get() bloqueantes.
            try:
                self.q.get_nowait()
                self.q.put_nowait(chunk)
            except queue.Empty:
                pass
            except queue.Full:
                pass
            self._log_queue_overflow()

    def _finalize_pending_utterance(self):
        """
        #7: roda DENTRO da AudioThread (nunca a GUI) — consome o audio ainda
        na fila, forca o Vosk a fechar a frase pendente com FinalResult() e
        grava o resultado no arquivo da SESSAO QUE FOI PAUSADA, capturado em
        _finalize_ctx no momento da pausa (nao no momento em que esta funcao
        roda, que pode ser depois de uma nova sessao ja ter comecado — #8).
        """
        with self._txt_lock:
            self._pending_finalize = False
            ctx = self._finalize_ctx
            self._finalize_ctx = None

        if not self.recognizer or not ctx:
            return

        try:
            # Drena o que sobrou na fila para dentro do reconhecedor.
            while True:
                try:
                    data = self.q.get_nowait()
                except queue.Empty:
                    break
                self.recognizer.AcceptWaveform(data)

            res = json.loads(self.recognizer.FinalResult())
            text = res.get('text', '')
            if text:
                final_text = self._translate_if_needed(text)
                if ctx["show_subtitles"] or self.is_translating:
                    self.final_ready.emit(final_text)
                try:
                    with open(ctx["txt_path"], 'a', encoding='utf-8') as f:
                        f.write(final_text + "\n")
                except OSError as exc:
                    log.exception(f"Falha ao gravar fala pendente da sessão pausada: {exc}")
        except Exception as exc:
            log.exception(f"Falha ao finalizar frase pendente: {exc}")
        finally:
            # Reseta o reconhecedor para a proxima sessao nao herdar
            # contexto acustico/estado da frase que acabamos de fechar.
            try:
                self.recognizer.Reset()
            except Exception:
                pass

    def _get_device_id(self):
        """
        Resolve qual dispositivo de entrada usar.

        BUG DE PRODUÇÃO (encontrado em diagnóstico com hardware real): antes
        esta função devolvia `input_device` (um ÍNDICE numérico do PortAudio)
        direto do config, sem validar nada. Índices do PortAudio NÃO são
        estáveis: mudam quando dispositivos aparecem/desaparecem — inclusive
        quando o próprio app abre o Baseus em modo exclusivo, o que remove o
        `hw:` da enumeração e desloca todos os índices seguintes.

        Consequência observada: o perfil tinha `input_device=15` (Baseus no
        momento em que foi salvo), mas na execução seguinte o índice 15 podia
        não existir, ou pior, apontar silenciosamente para OUTRO microfone
        (ex.: o da placa-mãe) — capturando do dispositivo errado sem nenhum
        aviso.

        Agora a resolução é por NOME (estável), com o índice servindo apenas
        como dica/fallback legado.
        """
        nome_salvo = self.config.get_audio("input_device_name")
        indice_salvo = self.config.get_audio("input_device")

        dispositivos = sd.query_devices()

        def eh_entrada(i):
            return 0 <= i < len(dispositivos) and dispositivos[i]["max_input_channels"] > 0

        # 1. Preferência: casar pelo NOME salvo (imune a remapeamento de índice).
        if nome_salvo:
            for idx, dev in enumerate(dispositivos):
                if dev["max_input_channels"] > 0 and dev["name"] == nome_salvo:
                    if idx != indice_salvo:
                        log.info(
                            f"Microfone '{nome_salvo}' mudou de índice "
                            f"({indice_salvo} -> {idx}); usando o índice atual."
                        )
                    return idx
            log.warning(
                f"Microfone salvo '{nome_salvo}' não está mais disponível. "
                "Usando o padrão do sistema."
            )
            return None

        # 2. Config legado (só índice, sem nome): valida antes de confiar.
        if indice_salvo is not None:
            if eh_entrada(indice_salvo):
                log.info(
                    f"Config legado sem nome de dispositivo; usando índice "
                    f"{indice_salvo} ('{dispositivos[indice_salvo]['name']}'). "
                    "Salve as configurações novamente para fixar o dispositivo por nome."
                )
                return indice_salvo
            log.warning(
                f"Índice de microfone salvo ({indice_salvo}) não é mais um "
                "dispositivo de entrada válido. Usando o padrão do sistema."
            )
            return None

        # 3. Sem nada salvo: tenta achar o Baseus automaticamente.
        for idx, dev in enumerate(dispositivos):
            if dev["max_input_channels"] > 0 and "baseus" in dev["name"].lower():
                return idx
        return None

    def _reset_level_monitor(self):
        """Zera o monitor de nível (ao (re)começar uma sessão ou stream)."""
        self._level_window_start = time.monotonic()
        self._level_peak = 0.0
        self._level_warned = False

    def _monitor_input_level(self, data):
        """
        Acompanha o nível do áudio recebido e avisa se estiver mudo.

        Detecta o modo de falha mais confuso de diagnosticar: o stream está
        aberto, os blocos chegam, mas são silêncio — o app "grava" e nada
        aparece na transcrição, sem nenhum erro. Agora isso vira um aviso
        explícito na tela e uma linha clara no log.
        """
        rms = _rms_int16(data)
        if rms > self._level_peak:
            self._level_peak = rms

        agora = time.monotonic()
        if agora - self._level_window_start < _LEVEL_CHECK_WINDOW_S:
            return

        pico = self._level_peak
        log.debug(f"Nível de entrada (pico na janela): rms={pico:.1f}")

        if pico < _LEVEL_SILENCE_RMS and not self._level_warned:
            self._level_warned = True
            log.warning(
                f"Gravando, mas o microfone não está enviando áudio "
                f"(pico rms={pico:.1f} em {_LEVEL_CHECK_WINDOW_S:.0f}s). "
                "Verifique o microfone selecionado e, no passador, se o "
                "microfone está realmente ativo. Use "
                "'python3 tools/diagnose_audio.py all' para comparar os "
                "caminhos de captura."
            )
            self.audio_warning.emit("⚠️ Microfone sem sinal! Verifique o dispositivo.")
        elif pico >= _LEVEL_SILENCE_RMS:
            # Voltou a chegar áudio: rearma o aviso para uma próxima queda.
            self._level_warned = False

        self._level_window_start = agora
        self._level_peak = 0.0

    def _fail_active_recording(self, motivo):
        """
        #15: ponto único para "abortar" uma gravação em andamento por causa
        de uma falha (stream ou escrita em disco). Sempre sincroniza
        is_recording e txt_path juntos, e emite audio_error para a UI
        desmarcar o estado de gravação — em vez de deixar is_recording=True
        "pendurado" sem nenhuma saída válida por baixo (o mesmo problema do
        #14, só que ocorrendo DEPOIS do início bem-sucedido da gravação).
        """
        with self._txt_lock:
            self.txt_path = None
            self._pending_finalize = False
            self._finalize_ctx = None
        self.is_recording = False
        self.audio_error.emit(motivo)

    def _wait_before_retry(self):
        """Espera até _STREAM_RETRY_DELAY_S, verificando self.running a cada
        100ms para não atrasar o encerramento do app quando stop() é chamado
        durante a espera de reconexão."""
        deadline = time.monotonic() + _STREAM_RETRY_DELAY_S
        while self.running and time.monotonic() < deadline:
            self.msleep(100)

    def run(self):
        # #16: loop EXTERNO — cada iteração abre um stream com o device_id
        # mais atual. Uma falha do stream ou um pedido de troca de
        # microfone encerram a iteração interna sem matar a QThread; o loop
        # externo decide se tenta de novo (device ainda existe) ou sai
        # (self.running == False).
        while self.running:
            try:
                device_id = self._get_device_id()
            except Exception as e:
                log.error(f"Erro ao identificar dispositivo de áudio: {e}")
                self.audio_warning.emit("⚠️ Falha ao detectar dispositivo de áudio!")
                self._wait_before_retry()
                continue

            log.info(f"Usando microfone ID: {device_id if device_id is not None else 'Padrão do Sistema'}")
            self._stream_restart_requested = False
            self._reset_level_monitor()

            try:
                with sd.RawInputStream(samplerate=16000, blocksize=4000, device=device_id,
                                       dtype='int16', channels=1, callback=self._audio_callback):
                    self._process_stream_loop()
            except Exception as e:
                # #15: antes só logava e a exceção matava a QThread — o
                # app ficava sem transcrição/tradução até reiniciar, sem
                # nenhuma indicação além do log. Agora avisa a UI e, se o
                # app ainda estiver rodando, tenta reabrir o stream.
                log.exception(f"Erro no SoundDevice: {e}")
                if self.is_recording:
                    self._fail_active_recording("⚠️ Gravação interrompida: falha no dispositivo de áudio!")
                else:
                    self.audio_error.emit("⚠️ Falha no dispositivo de áudio! Verifique o microfone.")
                self._wait_before_retry()
                continue

            # Saída "limpa" do loop interno: ou o app está encerrando
            # (self.running == False) ou foi um pedido de troca de
            # microfone (_stream_restart_requested) — nesse caso o loop
            # externo simplesmente reabre com o device_id atualizado.
            if self._stream_restart_requested:
                log.info("Reabrindo stream de áudio com o novo microfone selecionado...")

    def _process_stream_loop(self):
        """Loop interno: roda enquanto o stream atual permanecer válido."""
        while self.running and not self._stream_restart_requested:
            # #17: compara a versão PEDIDA com a última CARREGADA. Se uma
            # nova recarga for pedida enquanto _load_model() está rodando,
            # a versão pedida já estará adiante de novo na próxima
            # iteração — nada se perde, mesmo que o carregamento anterior
            # tenha acabado de terminar.
            with self._reload_lock:
                pending_version = self._reload_version
            if pending_version != self._loaded_reload_version:
                self._load_model()
                with self._reload_lock:
                    # Só marca como carregada a versão que já era a
                    # "pendente" quando começamos — se outra chegou durante
                    # o carregamento, a próxima iteração recarrega de novo.
                    if self._reload_version == pending_version:
                        self._loaded_reload_version = pending_version

            if self._pending_finalize:
                # #7: processado AQUI, na thread de audio — nunca em
                # set_recording(), que roda na thread da GUI e nao
                # pode tocar no KaldiRecognizer com seguranca
                # enquanto esta thread pode estar no meio de um
                # AcceptWaveform().
                self._finalize_pending_utterance()

            if not self.q.empty():
                data = self.q.get()

                # Vigia o nível de entrada sempre que a captura está ativa,
                # mesmo sem reconhecedor carregado — assim um microfone mudo
                # é detectado independentemente do estado do Vosk.
                if self.is_recording or self.is_translating:
                    self._monitor_input_level(data)

                if self.recognizer and (self.is_recording or self.is_translating):
                    # #8: captura txt_path/is_recording ANTES de
                    # traduzir. A traducao (rede/CPU) pode demorar; se
                    # o usuario pausar e iniciar uma NOVA sessao
                    # enquanto isso, self.txt_path ja mudou quando o
                    # resultado antigo chegasse — escrevendo a fala da
                    # sessao anterior no arquivo da sessao nova.
                    with self._txt_lock:
                        sessao_txt_path = self.txt_path
                        sessao_gravando = self.is_recording

                    if self.recognizer.AcceptWaveform(data):
                        res = json.loads(self.recognizer.Result())
                        text = res.get('text', '')
                        if text:
                            final_text = self._translate_if_needed(text)

                            # LÓGICA DE EXIBIÇÃO INTELIGENTE
                            if self.config.get_audio("show_subtitles", True) or self.is_translating:
                                self.final_ready.emit(final_text)

                            if sessao_txt_path and sessao_gravando:
                                try:
                                    with open(sessao_txt_path, 'a', encoding='utf-8') as f:
                                        f.write(final_text + "\n")
                                except OSError as exc:
                                    # #15: disco cheio / pendrive removido no
                                    # meio da aula. Antes só limpava o
                                    # txt_path e avisava com audio_warning,
                                    # deixando is_recording=True sem
                                    # nenhuma saída válida por baixo — a
                                    # mesma classe de bug do #14, só que
                                    # depois do início da sessão.
                                    log.exception(f"Falha ao gravar transcrição: {exc}")
                                    self._fail_active_recording(
                                        "⚠️ Gravação interrompida: falha ao salvar no arquivo da aula!"
                                    )
                    else:
                        res = json.loads(self.recognizer.PartialResult())
                        text = res.get('partial', '')
                        if text:
                            if self.config.get_audio("show_subtitles", True) or self.is_translating:
                                self.partial_ready.emit(self._translate_if_needed(text))
            else:
                self.msleep(10)

    def _resolve_source_lang(self):
        """
        #24: idioma de ORIGEM configurável. Antes era fixo em "pt" na
        chamada ao Argos — um modelo Vosk em inglês, por exemplo, tinha seu
        texto reconhecido enviado para tradução como se fosse português,
        produzindo traduções sem sentido. Lido do perfil ativo (chave
        "source_lang"), com fallback para "pt" por retrocompatibilidade.
        """
        return self.config.get_audio("source_lang", "pt")

    def _translate_if_needed(self, text):
        if self.is_translating and ARGOS_AVAILABLE and text:
            source_lang = self._resolve_source_lang()
            target_lang = self.config.get_audio("target_lang", "en")
            try:
                return argostranslate.translate.translate(text, source_lang, target_lang)
            except Exception as e:
                self.audio_warning.emit(
                    f"⚠️ Erro de Tradução: Pacote {source_lang}->{target_lang} ausente!")
                log.warning(f"Erro Argos: {e}")
                return text
        return text
        
    def stop(self):
        # #7: se o app for encerrado enquanto uma gravacao esta ativa (sem
        # passar por set_recording(False) antes), a fala pendente seria
        # perdida. Reaproveita o mesmo caminho de finalizacao do pause.
        self.set_recording(False)
        self.running = False
        # O retorno de wait() era descartado: se a thread não parasse, o app
        # seguia o cleanup e saía com a thread ainda viva.
        if not self.wait(3000):
            log.error("AudioThread não encerrou em 3s; forçando terminate().")
            self.terminate()
            self.wait(1000)
