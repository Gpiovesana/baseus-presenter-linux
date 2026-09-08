#!/bin/bash
set -euo pipefail

REPO="Gpiovesana/baseus-presenter-linux"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${BASEUS_INSTALL_DIR:-$SCRIPT_DIR}"
BACKUP_DIR="${INSTALL_DIR}_backup"
STAGING_DIR="${INSTALL_DIR}_staging"
STATE_FILE="${BASEUS_UPDATE_STATE_FILE:-${INSTALL_DIR}.update-state}"
LOCK_FILE="${BASEUS_UPDATE_LOCK_FILE:-${INSTALL_DIR}.update-lock}"

VERSION="${1:-}"
PID="${2:-}"
PREPARED_FILE="${3:-}"
VERSION="${VERSION#v}"

if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] ||
   [[ ! "$PID" =~ ^[0-9]+$ ]] || [[ -z "$PREPARED_FILE" ]]; then
    echo "❌ Uso: ./updater.sh <versao> <pid_do_app> <arquivo_de_estado>"
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "❌ Outra atualização já está em andamento."
    exit 1
fi

TMP_DIR="$(mktemp -d)"
STARTUP_READY_FILE="$TMP_DIR/startup-ready"
PREPARED=false
cleanup() {
    result=$?
    if [[ $result -ne 0 && "$PREPARED" == false ]]; then
        printf 'ERROR\n' > "$PREPARED_FILE"
    fi
    rm -rf -- "$TMP_DIR" "$STAGING_DIR"
}
trap cleanup EXIT

echo "🔄 Preparando Baseus Presenter v$VERSION..."
echo "📥 Baixando release..."
curl -sSL -f --connect-timeout 10 --max-time 180 \
    "https://github.com/$REPO/archive/refs/tags/v$VERSION.tar.gz" \
    -o "$TMP_DIR/release.tar.gz"

echo "📦 Extraindo e validando pacote..."
tar -xzf "$TMP_DIR/release.tar.gz" -C "$TMP_DIR"
EXTRACTED_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -print -quit)"
for file in app baseus_app.py requirements.txt version updater.sh; do
    if [[ ! -e "$EXTRACTED_DIR/$file" ]]; then
        echo "❌ Release inválida: '$file' não encontrado."
        exit 1
    fi
done

RELEASE_VERSION="$(tr -d '[:space:]' < "$EXTRACTED_DIR/version")"
if [[ "${RELEASE_VERSION#v}" != "$VERSION" ]]; then
    echo "❌ Versão do pacote não confere (esperada: $VERSION; encontrada: $RELEASE_VERSION)."
    exit 1
fi

rm -rf -- "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -a "$EXTRACTED_DIR/app" "$STAGING_DIR/"
cp "$EXTRACTED_DIR/baseus_app.py" "$EXTRACTED_DIR/requirements.txt" \
   "$EXTRACTED_DIR/version" "$EXTRACTED_DIR/updater.sh" "$STAGING_DIR/"
chmod +x "$STAGING_DIR/updater.sh"

echo "🐍 Preparando dependências em staging..."
python3 -m venv "$STAGING_DIR/.venv"
"$STAGING_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$STAGING_DIR/.venv/bin/python" -m pip install -q -r "$STAGING_DIR/requirements.txt"

# Entry points e scripts de ativação gravam o caminho absoluto da venv.
# Ajusta só arquivos de texto, ainda em staging: falha aqui preserva o app.
"$STAGING_DIR/.venv/bin/python" - "$STAGING_DIR/.venv" "$INSTALL_DIR/.venv" <<'PY_RELOCATE'
import os
import pathlib
import sys
old, new = map(os.fsencode, sys.argv[1:])
for path in (pathlib.Path(sys.argv[1]) / "bin").iterdir():
    if path.is_symlink() or not path.is_file():
        continue
    content = path.read_bytes()
    if b"\0" not in content and old in content:
        content.decode("utf-8")  # Recusa formato desconhecido, em vez de corromper.
        path.write_bytes(content.replace(old, new))
PY_RELOCATE

printf 'READY\n' > "$PREPARED_FILE"
PREPARED=true

echo "⏳ Aguardando o aplicativo encerrar..."
remaining=60
while kill -0 "$PID" 2>/dev/null; do
    sleep 0.5
    remaining=$((remaining - 1))
    if [[ $remaining -le 0 ]]; then
        echo "❌ O aplicativo não encerrou dentro do prazo."
        exit 1
    fi
done

# Recuperar antes deste ponto alteraria arquivos usados pelo aplicativo aberto.
if [[ -f "$STATE_FILE" && -d "$BACKUP_DIR" ]]; then
    echo "⚠️ Recuperando uma atualização anterior interrompida..."
    rm -rf -- "$INSTALL_DIR"
    mv "$BACKUP_DIR" "$INSTALL_DIR"
    rm -f -- "$STATE_FILE"
fi

PREVIOUS_VERSION="desconhecida"
if [[ -f "$INSTALL_DIR/version" ]]; then
    PREVIOUS_VERSION="$(tr -d '[:space:]' < "$INSTALL_DIR/version")"
fi

echo "🔄 Ativando a nova versão..."
rm -rf -- "$BACKUP_DIR"
# O estado só passa a existir depois de remover qualquer backup obsoleto.
printf 'pending\ntarget=%s\nprevious=%s\n' \
    "$VERSION" "$PREVIOUS_VERSION" > "$STATE_FILE"
mv "$INSTALL_DIR" "$BACKUP_DIR"

if ! mv "$STAGING_DIR" "$INSTALL_DIR"; then
    mv "$BACKUP_DIR" "$INSTALL_DIR"
    rm -f -- "$STATE_FILE"
    echo "❌ Falha ao ativar o staging; a versão anterior foi restaurada."
    exit 1
fi

# A aplicação escreve seu PID neste arquivo no primeiro ciclo do event loop.
( exec 9>&-; exec env BASEUS_UPDATE_READY_FILE="$STARTUP_READY_FILE" \
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/baseus_app.py" ) &
new_pid=$!

remaining=60
while [[ "$(cat "$STARTUP_READY_FILE" 2>/dev/null || true)" != "$new_pid" ]] && kill -0 "$new_pid" 2>/dev/null; do
    sleep 0.5
    remaining=$((remaining - 1))
    if [[ $remaining -le 0 ]]; then
        break
    fi
done

if [[ "$(cat "$STARTUP_READY_FILE" 2>/dev/null || true)" == "$new_pid" ]] &&
   kill -0 "$new_pid" 2>/dev/null; then
    rm -rf -- "$BACKUP_DIR"
    rm -f -- "$STATE_FILE"
    echo "✅ Atualização para v$VERSION concluída com sucesso."
    exit 0
fi

echo "⚠️ A nova versão não confirmou a inicialização; restaurando a anterior."
if kill -0 "$new_pid" 2>/dev/null; then
    kill "$new_pid" 2>/dev/null || true
    remaining=10
    while kill -0 "$new_pid" 2>/dev/null && [[ $remaining -gt 0 ]]; do
        sleep 0.2
        remaining=$((remaining - 1))
    done
    if kill -0 "$new_pid" 2>/dev/null; then
        kill -KILL "$new_pid" 2>/dev/null || true
    fi
    wait "$new_pid" 2>/dev/null || true
fi
rm -rf -- "$INSTALL_DIR"
mv "$BACKUP_DIR" "$INSTALL_DIR"
rm -f -- "$STATE_FILE"
( exec 9>&-; exec "$INSTALL_DIR/.venv/bin/python" \
    "$INSTALL_DIR/baseus_app.py" >/dev/null 2>&1 ) &
echo "✓ Rollback concluído e versão anterior reiniciada."
exit 1
