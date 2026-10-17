"""User-level GNOME extension setup; never restarts Shell or logs out."""
import ast
import re
import subprocess
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime

from .i18n import tr, configure_standalone

UUID = 'baseus-presenter@baseus.local'
FILES = ('metadata.json', 'extension.js', 'renderer.js', 'protocol.js')


def _validate_metadata(path):
    metadata = json.loads(path.read_text())
    if not isinstance(metadata, dict) or metadata.get('uuid') != UUID:
        raise ValueError(tr('Metadados da extensão inválidos: {0}', path))


def install_extension(source, destination):
    source, destination = Path(source), Path(destination)
    _validate_metadata(source / 'metadata.json')
    for name in FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    if destination.is_symlink():
        raise ValueError(tr('Destino da extensão não pode ser link simbólico'))
    if destination.exists():
        _validate_metadata(destination / 'metadata.json')
        if all((destination / name).is_file() and
               (destination / name).read_bytes() == (source / name).read_bytes()
               for name in FILES):
            return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.baseus-extension-', dir=destination.parent))
    backup = None
    try:
        for name in FILES:
            shutil.copy2(source / name, temporary / name)
        if destination.exists():
            backup_root = destination.parent.parent / 'baseus-extension-backups'
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / (destination.name + '.bak-' +
                datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            destination.rename(backup)
        try:
            os.replace(temporary, destination)
        except OSError:
            if backup:
                backup.rename(destination)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return backup


def extension_destination():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    if not data.is_absolute():
        data = Path.home() / '.local/share'
    return data / 'gnome-shell/extensions' / UUID


def prepare_wayland_extension():
    """Return a user-facing warning, or None when no further action is needed."""
    if 'gnome' not in os.environ.get('XDG_CURRENT_DESKTOP', '').lower():
        return tr('Os efeitos Wayland requerem GNOME 46. A navegação de slides continua disponível.')
    def run(args):
        return subprocess.run(args, capture_output=True, text=True, timeout=5)
    try:
        version = run(['gnome-shell', '--version'])
        if version.returncode or not re.search(r'\b46(?:\.|\b)', version.stdout):
            return tr('Esta extensão requer GNOME 46. A navegação de slides continua disponível.')
        owner_result = run(['gdbus', 'call', '--session', '--dest',
                            'org.freedesktop.DBus', '--object-path',
                            '/org/freedesktop/DBus', '--method',
                            'org.freedesktop.DBus.GetNameOwner', 'org.gnome.Shell'])
        if owner_result.returncode:
            raise RuntimeError(tr('GNOME Shell não está disponível nesta sessão'))
        owner = ast.literal_eval(owner_result.stdout.strip())[0]
        if not isinstance(owner, str) or not owner:
            raise ValueError(tr('Identificação da sessão GNOME inválida'))
        bus_result = run(['gdbus', 'call', '--session', '--dest',
                          'org.freedesktop.DBus', '--object-path',
                          '/org/freedesktop/DBus', '--method', 'org.freedesktop.DBus.GetId'])
        if bus_result.returncode:
            raise RuntimeError(tr('Não foi possível identificar a sessão D-Bus'))
        bus_id = ast.literal_eval(bus_result.stdout.strip())[0]
        if not isinstance(bus_id, str) or not bus_id:
            raise ValueError(tr('Identificação D-Bus inválida'))
        owner = bus_id + '/' + owner
        source = Path(__file__).resolve().parent.parent / 'extensions' / UUID
        destination = extension_destination()
        changed = not destination.exists() or any(
            not (destination / name).is_file() or
            (destination / name).read_bytes() != (source / name).read_bytes()
            for name in FILES)
        install_extension(source, destination)
        pending = destination / '.baseus-pending-shell'
        if changed:
            pending.write_text(owner, encoding='utf-8')
        needs_reload = pending.exists() and pending.read_text(encoding='utf-8') == owner
        if pending.exists() and not needs_reload:
            pending.unlink()
        enabled = run(['gnome-extensions', 'enable', UUID]).returncode == 0
        if not enabled:
            # A newly installed extension may only be discovered next login.
            # Preserve every other UUID in the user's settings.
            result = run(['gsettings', 'get', 'org.gnome.shell', 'enabled-extensions'])
            if result.returncode:
                raise RuntimeError(tr('Não foi possível consultar as extensões habilitadas'))
            value = ast.literal_eval(result.stdout.strip().removeprefix('@as '))
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError(tr('Lista de extensões inválida'))
            if UUID not in value:
                result = run(['gsettings', 'set', 'org.gnome.shell',
                              'enabled-extensions', repr(value + [UUID])])
                if result.returncode:
                    raise RuntimeError(tr('Não foi possível habilitar a extensão'))
        if needs_reload or not enabled:
            return tr('Extensão Baseus preparada. Salve seu trabalho, saia e entre na sessão '
                      'e abra o Baseus novamente para carregar os efeitos atualizados. '
                      'A navegação de slides continua disponível.')
        return None
    except (OSError, ValueError, SyntaxError, IndexError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        return tr('Não foi possível preparar a extensão GNOME: {0}. A navegação de slides continua disponível.', error)


def main():
    configure_standalone()
    source = Path(__file__).resolve().parent.parent / 'extensions' / UUID
    destination = extension_destination()
    backup = install_extension(source, destination)
    print(tr('Extensão instalada em {0}', destination))
    if backup:
        print(tr('Backup: {0}', backup))
    print(tr('Não foi ativada. Se nova ou atualizada, salve seu trabalho e faça logout/login.'))
    print(tr('Depois: {0}', f'gnome-extensions enable {UUID}'))


if __name__ == '__main__':
    main()
