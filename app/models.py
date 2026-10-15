"""Vosk catalog mutations and Argos package workers; dialogs stay in gui.py."""
import contextlib
import socket
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from .i18n import tr
from .logger import get_logger

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False


log = get_logger(__name__)


def find_model(config, path):
    return next((model for model in config.get('models', []) if model.get('path') == path), {})


def add_model(config, path, label, language):
    with config.mutate() as data:
        models = data.setdefault('models', [])
        models[:] = [model for model in models if model.get('path') != path]
        models.append({'path': path, 'label': label, 'language': language})
        data['profiles'][data['active_profile']]['audio']['selected_model_path'] = path


def set_model_language(config, path, language):
    with config.mutate() as data:
        models = data.setdefault('models', [])
        entry = next((model for model in models if model.get('path') == path), None)
        if entry is None:
            entry = {'path': path, 'label': path}
            models.append(entry)
        entry['language'] = language


def remove_model(config, path):
    with config.mutate() as data:
        data['models'] = [model for model in data.get('models', []) if model.get('path') != path]
        for profile in data['profiles'].values():
            if profile['audio'].get('selected_model_path') == path:
                profile['audio']['selected_model_path'] = ''


def has_translation(source, target):
    installed = argostranslate.translate.get_installed_languages()
    origin = next((language for language in installed if language.code == source), None)
    destination = next((language for language in installed if language.code == target), None)
    return bool(origin and destination and origin.get_translation(destination))


# #25: timeouts para as operações de rede do Argos. A biblioteca usa urllib
# internamente e NÃO expõe parâmetro de timeout, então o único ponto de
# controle é o default de socket. Sem isto, uma conexão que "pendura"
# (servidor aceita o TCP mas nunca responde) deixa a thread viva
# indefinidamente — e o stop_threads() do encerramento acaba tendo de
# recorrer a terminate().
ARGOS_INDEX_TIMEOUT_S = 15      # listar/atualizar o índice de pacotes
ARGOS_DOWNLOAD_TIMEOUT_S = 120  # baixar o pacote (~30MB)


_socket_timeout_lock = threading.RLock()


@contextlib.contextmanager
def socket_timeout(seconds):
    """
    Aplica um timeout de socket ao redor de uma operação de rede.

    ATENÇÃO: setdefaulttimeout é GLOBAL do processo. Isso só é aceitável
    para as operações Argos serializadas por esta trava. O atualizador
    informa seu próprio timeout explicitamente; outras operações de rede
    também devem fazê-lo. O valor anterior é sempre restaurado.
    """
    with _socket_timeout_lock:
        anterior = socket.getdefaulttimeout()
        socket.setdefaulttimeout(seconds)
        try:
            yield
        finally:
            socket.setdefaulttimeout(anterior)


class LanguageLoadThread(QThread):
    """
    Carrega o índice de idiomas do Argos FORA da thread da GUI.

    populate_languages() rodava síncrono no __init__ da MainWindow. Como
    get_available_packages() faz I/O de rede/disco, a janela congelava até o
    timeout quando não havia internet — sem qualquer feedback ao usuário.
    """
    loaded = pyqtSignal(list)   # [(origem, nome_destino, codigo_destino), ...]
    failed = pyqtSignal(str)

    def run(self):
        try:
            # #25: sem timeout, esta thread podia ficar pendurada para
            # sempre numa conexão lenta/travada, sobrevivendo ao
            # encerramento do app.
            with socket_timeout(ARGOS_INDEX_TIMEOUT_S):
                argostranslate.package.update_package_index()
                pacotes = argostranslate.package.get_available_packages()
            idiomas = [(p.from_code, p.to_name, p.to_code) for p in pacotes]
            self.loaded.emit(idiomas)
        except Exception as e:
            log.exception(f"Erro ao carregar idiomas do Argos: {e}")
            self.failed.emit(str(e))


class PackageInstallThread(QThread):
    finished = pyqtSignal(bool, str)
    def __init__(self, from_code, to_code):
        super().__init__()
        self.from_code = from_code
        self.to_code = to_code

    def run(self):
        try:
            # #25: `update_package_index()` e `download()` fazem I/O de rede
            # sem timeout próprio. Um servidor que aceita a conexão mas
            # nunca responde mantinha esta thread viva indefinidamente,
            # forçando o terminate() no encerramento do app.
            with socket_timeout(ARGOS_INDEX_TIMEOUT_S):
                argostranslate.package.update_package_index()
                available = argostranslate.package.get_available_packages()

            pkg = next((p for p in available if p.from_code == self.from_code and p.to_code == self.to_code), None)
            if not pkg:
                self.finished.emit(False, tr('Pacote não encontrado no servidor.'))
                return

            # Timeout mais generoso: aqui são ~30MB. O timeout do socket é
            # por operação de leitura, não para o download inteiro, então
            # ele interrompe um servidor travado sem abortar um download
            # legítimo porém lento.
            with socket_timeout(ARGOS_DOWNLOAD_TIMEOUT_S):
                path = pkg.download()

            argostranslate.package.install_from_path(path)
            self.finished.emit(True, tr('Instalação concluída!'))
        except socket.timeout:
            log.error("Timeout de rede ao baixar o pacote de idioma do Argos.")
            self.finished.emit(
                False, tr('Tempo de conexão esgotado. Verifique sua internet e tente de novo.'))
        except Exception as e:
            log.exception(f"Falha na instalação do pacote de idioma: {e}")
            self.finished.emit(False, str(e))

