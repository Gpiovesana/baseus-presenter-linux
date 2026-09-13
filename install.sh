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
REQUESTED_INSTALL_DIR="${BASEUS_INSTALL_DIR:-$HOME/BaseusPresenter}"
INSTALL_DIR="$(realpath -m -- "$REQUESTED_INSTALL_DIR")"
CANONICAL_HOME="$(realpath -m -- "$HOME")"
DESKTOP_FILE="baseus-presenter.desktop"
LOCK_FILE="${BASEUS_UPDATE_LOCK_FILE:-${INSTALL_DIR}.update-lock}"
ENABLE_AUTOSTART=""
for arg in "$@"; do
    case "$arg" in
        --autostart) ENABLE_AUTOSTART=true ;;
        --no-autostart) ENABLE_AUTOSTART=false ;;
        *) say "❌ ERRO: opção desconhecida: $arg" "❌ ERROR: unknown option: $arg"; exit 2 ;;
    esac
done

say "🚀 Iniciando a instalação do Baseus Presenter..." "🚀 Starting Baseus Presenter installation..."
if [[ "$EUID" -eq 0 ]]; then
    say "❌ ERRO: Não execute este instalador como root (sudo)." "❌ ERROR: Do not run this installer as root (sudo)."
    say "   O script pedirá a senha do sudo sozinho quando precisar." "   The script will request your sudo password when needed."
    exit 1
fi
if [[ ! "$REQUESTED_INSTALL_DIR" = /* ]] || [[ "$INSTALL_DIR" == "/" ]] ||
   [[ "$INSTALL_DIR" == "$CANONICAL_HOME" ]] || [[ "$REQUESTED_INSTALL_DIR" == *$'\n'* ]] ||
   [[ -L "$REQUESTED_INSTALL_DIR" ]]; then
    say "❌ ERRO: diretório de instalação inseguro: $INSTALL_DIR" "❌ ERROR: unsafe installation directory: $INSTALL_DIR"
    exit 1
fi
# Protege repositórios normais e worktrees (onde .git é um arquivo), inclusive
# quando o destino aponta para uma subpasta de um checkout.
CHECKOUT_PATH="$INSTALL_DIR"
while [[ "$CHECKOUT_PATH" != "/" ]]; do
    if [[ -f "$CHECKOUT_PATH/.git" ]] || [[ -L "$CHECKOUT_PATH/.git" ]] ||
       [[ -f "$CHECKOUT_PATH/.git/HEAD" ]]; then
        say "❌ ERRO: $INSTALL_DIR está dentro de um checkout Git; instalação cancelada." "❌ ERROR: $INSTALL_DIR is inside a Git checkout; installation cancelled."
        exit 1
    fi
    CHECKOUT_PATH="$(dirname -- "$CHECKOUT_PATH")"
done
if [[ -e "$INSTALL_DIR" ]] &&
   { [[ ! -f "$INSTALL_DIR/baseus_app.py" ]] || [[ ! -f "$INSTALL_DIR/version" ]]; }; then
    say "❌ ERRO: o destino existe, mas não parece uma instalação do Baseus Presenter." "❌ ERROR: the destination exists but does not appear to be a Baseus Presenter installation."
    exit 1
fi
if ! command -v apt >/dev/null 2>&1; then
    say "❌ ERRO: Este instalador requer uma distribuição baseada em Debian/Ubuntu (Zorin, Mint, etc)." "❌ ERROR: This installer requires a Debian/Ubuntu-based distribution (Zorin, Mint, etc)."
    exit 1
fi

if [[ -z "$ENABLE_AUTOSTART" ]]; then
    if ! exec 3<>/dev/tty 2>/dev/null; then
        say "❌ ERRO: não há um terminal disponível para escolher a inicialização automática." "❌ ERROR: no terminal is available to choose automatic startup."
        say "   Execute novamente com --autostart ou --no-autostart." "   Run again with --autostart or --no-autostart."
        exit 2
    fi
    while true; do
        ui_text "Deseja iniciar o Baseus Presenter automaticamente ao entrar no sistema? [y/n]: " "Start Baseus Presenter automatically when you sign in? [y/n]: " >&3
        if ! IFS= read -r AUTOSTART_ANSWER <&3; then
            exec 3>&-
            say "❌ ERRO: não foi possível ler a escolha de inicialização automática." "❌ ERROR: could not read the automatic startup choice."
            exit 2
        fi
        case "${AUTOSTART_ANSWER,,}" in
            y) ENABLE_AUTOSTART=true; break ;;
            n) ENABLE_AUTOSTART=false; break ;;
            *) say "Resposta inválida. Digite y ou n." "Invalid answer. Enter y or n." >&3 ;;
        esac
    done
    exec 3>&-
fi

mkdir -p -- "$(dirname -- "$INSTALL_DIR")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    say "❌ Outra instalação ou atualização já está em andamento." "❌ Another installation or update is already in progress."
    exit 1
fi

say "📦 1/6 Instalando dependências de sistema..." "📦 1/6 Installing system dependencies..."
sudo apt update
sudo apt install -y curl python3 python3-venv python3-pip python3-dev build-essential \
    libportaudio2 portaudio19-dev libxcb-cursor0 libxcb-xinerama0 xterm zenity

say "🛡️ 2/6 Configurando permissões de hardware (udev + uaccess)..." "🛡️ 2/6 Configuring hardware permissions (udev + uaccess)..."
sudo tee /etc/udev/rules.d/99-baseus-presenter.rules > /dev/null <<'EOF'
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", TAG+="uaccess"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

WORK_DIR="$(mktemp -d "${INSTALL_DIR}.prepare.XXXXXX")"
STAGING_DIR="$WORK_DIR/staging"
BACKUP_DIR=""
ACTIVATED=false
APP_LOCK_PID=""
cleanup() {
    result=$?
    # A trava do app é mantida até terminar qualquer rollback.
    if [[ $result -ne 0 && "$ACTIVATED" == true ]]; then
        rm -rf -- "$INSTALL_DIR"
        if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
            mv -- "$BACKUP_DIR" "$INSTALL_DIR"
        fi
        say "❌ A ativação falhou; a instalação anterior foi restaurada." "❌ Activation failed; the previous installation was restored."
    fi
    rm -rf -- "$WORK_DIR"
    if [[ $result -eq 0 && -n "$BACKUP_DIR" ]]; then rm -rf -- "$BACKUP_DIR"; fi
    if [[ -n "$APP_LOCK_PID" ]]; then
        kill "$APP_LOCK_PID" 2>/dev/null || true
        wait "$APP_LOCK_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

say "📥 3/6 Consultando a última release estável..." "📥 3/6 Checking the latest stable release..."
curl -sS -fL --connect-timeout 10 --max-time 60 \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/releases/latest" -o "$WORK_DIR/release.json"
RELEASE_TAG="$(python3 - "$WORK_DIR/release.json" <<'PY_RELEASE'
import json, re, sys
try:
    with open(sys.argv[1], encoding="utf-8") as source:
        release = json.load(source)
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"resposta inválida da API do GitHub: {error}")
if not isinstance(release, dict):
    raise SystemExit("resposta inválida da API do GitHub: objeto esperado")
tag = release.get("tag_name")
if release.get("draft") is not False or release.get("prerelease") is not False:
    raise SystemExit("a release retornada não é estável e publicada")
if not isinstance(tag, str) or not re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,2}", tag):
    raise SystemExit("tag da release ausente ou inválida")
print(tag)
PY_RELEASE
)" || { say "❌ ERRO: não foi possível validar a última release." "❌ ERROR: could not validate the latest release."; exit 1; }

say "📦 Baixando e validando release $RELEASE_TAG..." "📦 Downloading and validating release $RELEASE_TAG..."
curl -sS -fL --connect-timeout 10 --max-time 180 \
    "https://github.com/$REPO/archive/refs/tags/$RELEASE_TAG.tar.gz" \
    -o "$WORK_DIR/release.tar.gz"
mkdir -p "$WORK_DIR/extracted"
tar -xzf "$WORK_DIR/release.tar.gz" -C "$WORK_DIR/extracted"
EXTRACTED_DIR="$(find "$WORK_DIR/extracted" -mindepth 1 -maxdepth 1 -type d -print -quit)"
for file in app app/uninstall.py baseus_app.py requirements.txt version updater.sh uninstall.sh; do
    if [[ -z "$EXTRACTED_DIR" || ! -e "$EXTRACTED_DIR/$file" ]]; then
        say "❌ ERRO: release inválida: '$file' não encontrado." "❌ ERROR: invalid release: '$file' not found."
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
PACKAGE_VERSION="$(tr -d '[:space:]' < "$EXTRACTED_DIR/version")"
if [[ "${PACKAGE_VERSION#v}" != "${RELEASE_TAG#v}" ]]; then
    say "❌ ERRO: versão do pacote não confere com a tag $RELEASE_TAG." "❌ ERROR: package version does not match tag $RELEASE_TAG."
    exit 1
fi

mkdir -p "$STAGING_DIR"
cp -a "$EXTRACTED_DIR/app" "$STAGING_DIR/"
cp "$EXTRACTED_DIR/baseus_app.py" "$EXTRACTED_DIR/requirements.txt" \
   "$EXTRACTED_DIR/version" "$EXTRACTED_DIR/updater.sh" \
   "$EXTRACTED_DIR/uninstall.sh" "$STAGING_DIR/"
chmod +x "$STAGING_DIR/updater.sh" "$STAGING_DIR/uninstall.sh"

say "🐍 4/6 Preparando ambiente virtual e dependências..." "🐍 4/6 Preparing virtual environment and dependencies..."
python3 -m venv "$STAGING_DIR/.venv"
"$STAGING_DIR/.venv/bin/python" -m pip install --upgrade pip
"$STAGING_DIR/.venv/bin/python" -m pip install -r "$STAGING_DIR/requirements.txt"
"$STAGING_DIR/.venv/bin/python" - "$STAGING_DIR/.venv" "$INSTALL_DIR/.venv" <<'PY_RELOCATE'
import os, pathlib, sys
old, new = map(os.fsencode, sys.argv[1:])
for path in (pathlib.Path(sys.argv[1]) / "bin").iterdir():
    if path.is_symlink() or not path.is_file():
        continue
    content = path.read_bytes()
    if b"\0" not in content and old in content:
        content.decode("utf-8")
        path.write_bytes(content.replace(old, new))
PY_RELOCATE

# flock do instalador/updater e lockf do app são travas diferentes. Este
# processo mantém a trava POSIX de instância durante toda a ativação.
if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" ]]; then
    APP_LOCK_FILE="$XDG_RUNTIME_DIR/baseus_presenter.lock"
else
    APP_LOCK_FILE="/tmp/baseus_presenter-$(id -u).lock"
fi
python3 - "$APP_LOCK_FILE" "$WORK_DIR/app-lock-ready" "$$" 9>&- <<'PY_APP_LOCK' &
import fcntl, os, pathlib, sys, time
try:
    lock = open(sys.argv[1], "a+")
    fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    raise SystemExit("Feche o Baseus Presenter antes de reinstalar; não foi possível obter a trava do aplicativo.")
pathlib.Path(sys.argv[2]).touch()
while True:
    try:
        os.kill(int(sys.argv[3]), 0)
    except ProcessLookupError:
        break
    time.sleep(0.1)
PY_APP_LOCK
APP_LOCK_PID=$!
for _ in {1..100}; do
    [[ -f "$WORK_DIR/app-lock-ready" ]] && break
    if ! kill -0 "$APP_LOCK_PID" 2>/dev/null; then
        say "❌ Não foi possível obter a trava do aplicativo. A instalação anterior foi preservada." "❌ Could not acquire the application lock. The previous installation was preserved."
        exit 1
    fi
    sleep 0.05
done
if [[ ! -f "$WORK_DIR/app-lock-ready" ]]; then
    say "❌ Tempo esgotado ao obter a trava do aplicativo." "❌ Timed out while acquiring the application lock."
    exit 1
fi

say "🔄 Ativando release $RELEASE_TAG..." "🔄 Activating release $RELEASE_TAG..."
if [[ -e "$INSTALL_DIR" ]]; then
    BACKUP_DIR="$(mktemp -d "${INSTALL_DIR}.backup.XXXXXX")"
    rmdir -- "$BACKUP_DIR"
    mv -- "$INSTALL_DIR" "$BACKUP_DIR"
fi
if ! mv -- "$STAGING_DIR" "$INSTALL_DIR"; then
    if [[ -n "$BACKUP_DIR" ]]; then mv -- "$BACKUP_DIR" "$INSTALL_DIR"; fi
    BACKUP_DIR=""
    say "❌ ERRO: não foi possível ativar a nova instalação." "❌ ERROR: could not activate the new installation."
    exit 1
fi
ACTIVATED=true

say "🖥️ 5/6 Configurando lançador..." "🖥️ 5/6 Configuring launcher..."
PYTHON="$INSTALL_DIR/.venv/bin/python"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$DESKTOP_DIR"
DESKTOP_TMP="$WORK_DIR/$DESKTOP_FILE"
cat > "$DESKTOP_TMP" <<EOF
[Desktop Entry]
Type=Application
Name=Baseus Presenter
Comment=Unofficial driver for the Baseus Orange Dot AI presenter
Comment[pt]=Driver não-oficial para o passador Baseus Orange Dot AI
Exec="$PYTHON" "$INSTALL_DIR/baseus_app.py"
Path=$INSTALL_DIR
Icon=input-tablet
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
chmod +x "$DESKTOP_TMP"
cp "$DESKTOP_TMP" "$DESKTOP_DIR/$DESKTOP_FILE"
rm -f "$AUTOSTART_DIR/$DESKTOP_FILE"
if [[ "$ENABLE_AUTOSTART" == true ]]; then
    mkdir -p "$AUTOSTART_DIR"
    cp "$DESKTOP_TMP" "$AUTOSTART_DIR/$DESKTOP_FILE"
    say "✓ Inicialização automática ativada." "✓ Automatic startup enabled."
else
    say "✓ Inicialização automática desativada (use o menu de aplicativos pra abrir)." "✓ Automatic startup disabled (open from the applications menu)."
fi
python3 "$INSTALL_DIR/app/uninstall.py" --register-desktop "$INSTALL_DIR"

echo ""
say "✅ 6/6 INSTALAÇÃO DA RELEASE $RELEASE_TAG CONCLUÍDA!" "✅ 6/6 RELEASE $RELEASE_TAG INSTALLATION COMPLETE!"
echo ""
say "🔌 Desconecte e conecte o passador Baseus de novo pra aplicar as permissões." "🔌 Unplug and reconnect the Baseus presenter to apply permissions."
say "   Não precisa reiniciar o computador nem fazer logout." "   You do not need to restart the computer or sign out."
