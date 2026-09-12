#!/bin/bash
set -euo pipefail

# Standalone installer messages cannot depend on downloaded Python modules.
UI_LANGUAGE="${BASEUS_UI_LANGUAGE:-auto}"
if [[ "$UI_LANGUAGE" != pt && "$UI_LANGUAGE" != en ]]; then
    UI_LANGUAGE=en
    LANGUAGE_CANDIDATES="${LANGUAGE:-}:${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}"
    IFS=: read -r -a UI_CANDIDATES <<< "$LANGUAGE_CANDIDATES"
    for candidate in "${UI_CANDIDATES[@]}"; do
        case "$candidate" in
            pt|pt_*|pt-*|pt.*) UI_LANGUAGE=pt; break ;;
            en|en_*|en-*|en.*) UI_LANGUAGE=en; break ;;
        esac
    done
fi
ui_text() {
    if [[ "$UI_LANGUAGE" == pt ]]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}
say() { ui_text "$@"; printf '\n'; }

REPO="Gpiovesana/baseus-presenter-linux"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(realpath -e -- "${BASEUS_INSTALL_DIR:-$SCRIPT_DIR}")"
BACKUP_DIR="${INSTALL_DIR}_backup"
STAGING_DIR="${INSTALL_DIR}_staging"
STATE_FILE="${BASEUS_UPDATE_STATE_FILE:-${INSTALL_DIR}.update-state}"
LOCK_FILE="${BASEUS_UPDATE_LOCK_FILE:-${INSTALL_DIR}.update-lock}"

RELEASE_TAG="${1:-}"
PID="${2:-}"
PREPARED_FILE="${3:-}"
AUTOSTART_CHOICE="${4:-keep}"
VERSION="${RELEASE_TAG#v}"

case "$AUTOSTART_CHOICE" in
    keep|enable|disable) ;;
    *) say "❌ Escolha de inicialização automática inválida." "❌ Invalid automatic startup choice."; exit 2 ;;
esac

# Só é chamado após a confirmação de abertura da nova versão.
# A substituição atômica mantém o atalho anterior caso a gravação falhe.
configure_autostart() {
    [[ "$AUTOSTART_CHOICE" == keep ]] && return 0
    python3 - "$INSTALL_DIR" "$AUTOSTART_CHOICE" <<'PY_AUTOSTART'
import os
import pathlib
import sys
import tempfile

installation = pathlib.Path(sys.argv[1])
entry = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config") / "autostart/baseus-presenter.desktop"
if sys.argv[2] == "disable":
    entry.unlink(missing_ok=True)
else:
    def quote(value):
        value = str(value).replace("%", "%%")
        for char in ("\\", '"', "`", "$"):
            value = value.replace(char, "\\" + char)
        return '"' + value.replace("\\", "\\\\") + '"'

    entry.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".baseus-autostart-", dir=entry.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(
                "[Desktop Entry]\nType=Application\nName=Baseus Presenter\n"
                f"Exec={quote(installation / '.venv/bin/python')} {quote(installation / 'baseus_app.py')}\n"
                "Icon=input-tablet\nTerminal=false\nCategories=Utility;\nStartupNotify=false\n")
        os.replace(temporary, entry)
    finally:
        pathlib.Path(temporary).unlink(missing_ok=True)
PY_AUTOSTART
}

if [[ ! "$VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] ||
   [[ ! "$PID" =~ ^[0-9]+$ ]] || [[ -z "$PREPARED_FILE" ]]; then
    say "❌ Uso: ./updater.sh <versao> <pid_do_app> <arquivo_de_estado>" "❌ Usage: ./updater.sh <version> <app_pid> <status_file>"
    exit 1
fi

# Proteção independente da GUI: nunca substitui um checkout, nem um worktree.
if [[ "$INSTALL_DIR" == / || "$INSTALL_DIR" == "$(realpath -- "$HOME")" ||
      ! -f "$INSTALL_DIR/baseus_app.py" || ! -f "$INSTALL_DIR/version" ]]; then
    say "❌ Diretório de instalação inválido." "❌ Invalid installation directory."
    exit 1
fi
CHECK_DIR="$INSTALL_DIR"
while :; do
    if [[ -f "$CHECK_DIR/.git" || -f "$CHECK_DIR/.git/HEAD" || -L "$CHECK_DIR/.git" ]]; then
        say "❌ Atualização bloqueada em checkout de desenvolvimento. Use o Git." "❌ Updates are blocked in development checkouts. Use Git."
        exit 1
    fi
    [[ "$CHECK_DIR" == / ]] && break
    CHECK_DIR="$(dirname -- "$CHECK_DIR")"
done

# O shell permanece em uma pasta estável durante a troca da instalação.
cd -- "$(dirname -- "$INSTALL_DIR")"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    say "❌ Outra atualização já está em andamento." "❌ Another update is already in progress."
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

say "🔄 Preparando Baseus Presenter v$VERSION..." "🔄 Preparing Baseus Presenter v$VERSION..."
say "📥 Baixando release..." "📥 Downloading release..."
curl -sSL -f --connect-timeout 10 --max-time 180 \
    "https://github.com/$REPO/archive/refs/tags/$RELEASE_TAG.tar.gz" \
    -o "$TMP_DIR/release.tar.gz"

say "📦 Extraindo e validando pacote..." "📦 Extracting and validating package..."
tar -xzf "$TMP_DIR/release.tar.gz" -C "$TMP_DIR"
EXTRACTED_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -print -quit)"
for file in app app/uninstall.py baseus_app.py requirements.txt version updater.sh uninstall.sh; do
    if [[ ! -e "$EXTRACTED_DIR/$file" ]]; then
        say "❌ Release inválida: '$file' não encontrado." "❌ Invalid release: '$file' not found."
        exit 1
    fi
done

if [[ -f "$EXTRACTED_DIR/app/i18n.py" ]]; then
    for file in app/translations/baseus_en.ts app/translations/baseus_en.qm app/translations/baseus_pt.ts app/translations/baseus_pt.qm; do
        if [[ ! -s "$EXTRACTED_DIR/$file" ]]; then
            say "❌ Tradução ausente no pacote: $file" "❌ Translation missing from package: $file"
            exit 1
        fi
    done
fi
RELEASE_VERSION="$(tr -d '[:space:]' < "$EXTRACTED_DIR/version")"
if [[ "${RELEASE_VERSION#v}" != "$VERSION" ]]; then
    say "❌ Versão do pacote não confere (esperada: $VERSION; encontrada: $RELEASE_VERSION)." "❌ Package version mismatch (expected: $VERSION; found: $RELEASE_VERSION)."
    exit 1
fi

rm -rf -- "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -a "$EXTRACTED_DIR/app" "$STAGING_DIR/"
cp "$EXTRACTED_DIR/baseus_app.py" "$EXTRACTED_DIR/requirements.txt" \
   "$EXTRACTED_DIR/version" "$EXTRACTED_DIR/updater.sh" \
   "$EXTRACTED_DIR/uninstall.sh" "$STAGING_DIR/"
chmod +x "$STAGING_DIR/updater.sh" "$STAGING_DIR/uninstall.sh"

say "🐍 Preparando dependências em staging..." "🐍 Preparing dependencies..."
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

say "⏳ Aguardando o aplicativo encerrar..." "⏳ Waiting for the application to close..."
remaining=60
while kill -0 "$PID" 2>/dev/null; do
    sleep 0.5
    remaining=$((remaining - 1))
    if [[ $remaining -le 0 ]]; then
        say "❌ O aplicativo não encerrou dentro do prazo." "❌ The application did not close within the time limit."
        exit 1
    fi
done

# Recuperar antes deste ponto alteraria arquivos usados pelo aplicativo aberto.
if [[ -f "$STATE_FILE" && -d "$BACKUP_DIR" ]]; then
    say "⚠️ Recuperando uma atualização anterior interrompida..." "⚠️ Recovering an interrupted previous update..."
    rm -rf -- "$INSTALL_DIR"
    mv "$BACKUP_DIR" "$INSTALL_DIR"
    rm -f -- "$STATE_FILE"
fi

PREVIOUS_VERSION="desconhecida"
if [[ -f "$INSTALL_DIR/version" ]]; then
    PREVIOUS_VERSION="$(tr -d '[:space:]' < "$INSTALL_DIR/version")"
fi

say "🔄 Ativando a nova versão..." "🔄 Activating the new version..."
rm -rf -- "$BACKUP_DIR"
# O estado só passa a existir depois de remover qualquer backup obsoleto.
printf 'pending\ntarget=%s\nprevious=%s\n' \
    "$VERSION" "$PREVIOUS_VERSION" > "$STATE_FILE"
mv "$INSTALL_DIR" "$BACKUP_DIR"

if ! mv "$STAGING_DIR" "$INSTALL_DIR"; then
    mv "$BACKUP_DIR" "$INSTALL_DIR"
    rm -f -- "$STATE_FILE"
    say "❌ Falha ao ativar o staging; a versão anterior foi restaurada." "❌ Failed to activate the prepared update; the previous version was restored."
    ( exec 9>&-; cd -- "$INSTALL_DIR"; exec "$INSTALL_DIR/.venv/bin/python" \
        "$INSTALL_DIR/baseus_app.py" >/dev/null 2>&1 ) &
    exit 1
fi

# A aplicação escreve seu PID neste arquivo no primeiro ciclo do event loop.
( exec 9>&-; cd -- "$INSTALL_DIR"; exec env BASEUS_UPDATE_READY_FILE="$STARTUP_READY_FILE" \
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
   kill -0 "$new_pid" 2>/dev/null && configure_autostart; then
    if ! python3 "$INSTALL_DIR/app/uninstall.py" --register-desktop "$INSTALL_DIR"; then
        say "⚠️ Não foi possível registrar o atalho de desinstalação; o aplicativo tentará novamente ao abrir." "⚠️ Could not register the uninstall shortcut; the application will retry when opened."
    fi
    rm -rf -- "$BACKUP_DIR"
    rm -f -- "$STATE_FILE"
    say "✅ Atualização para v$VERSION concluída com sucesso." "✅ Update to v$VERSION completed successfully."
    exit 0
fi

say "⚠️ Falha ao iniciar ou configurar a nova versão; restaurando a anterior." "⚠️ Failed to start or configure the new version; restoring the previous one."
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
( exec 9>&-; cd -- "$INSTALL_DIR"; exec "$INSTALL_DIR/.venv/bin/python" \
    "$INSTALL_DIR/baseus_app.py" >/dev/null 2>&1 ) &
say "✓ Rollback concluído e versão anterior reiniciada." "✓ Rollback complete; the previous version was restarted."
exit 1
