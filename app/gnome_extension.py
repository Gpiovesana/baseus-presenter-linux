"""Explicit user-level installation; never enables an extension or restarts Shell."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime

UUID = 'baseus-presenter@baseus.local'
FILES = ('metadata.json', 'extension.js', 'renderer.js', 'protocol.js')


def install_extension(source, destination):
    source, destination = Path(source), Path(destination)
    if json.loads((source / 'metadata.json').read_text())['uuid'] != UUID:
        raise ValueError('UUID da extensão de origem inválido')
    for name in FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    if destination.is_symlink():
        raise ValueError('Destino da extensão não pode ser link simbólico')
    if destination.exists():
        if json.loads((destination / 'metadata.json').read_text())['uuid'] != UUID:
            raise ValueError('Destino pertence a outra extensão')
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


def main():
    source = Path(__file__).resolve().parent.parent / 'extensions' / UUID
    destination = Path.home() / '.local/share/gnome-shell/extensions' / UUID
    backup = install_extension(source, destination)
    print(f'Extensão instalada em {destination}')
    if backup:
        print(f'Backup: {backup}')
    print('Não foi ativada. Se nova ou atualizada, salve seu trabalho e faça logout/login.')
    print(f'Depois: gnome-extensions enable {UUID}')


if __name__ == '__main__':
    main()
