#!/bin/bash
set -euo pipefail

# Ajuste aqui quando "dev" for promovida a "main" oficialmente (ver v2.0.0).
REPO_URL="https://github.com/Gpiovesana/baseus-presenter-linux.git"
BRANCH="dev"
INSTALL_DIR="$HOME/BaseusPresenter"
DESKTOP_FILE="baseus-presenter.desktop"

# --no-autostart: instala tudo normalmente, mas não sobe sozinho no login.
ENABLE_AUTOSTART=true
for arg in "$@"; do
    case "$arg" in
        --no-autostart) ENABLE_AUTOSTART=false ;;
    esac
done

echo "🚀 Iniciando a instalação do Baseus Presenter..."

if [[ "$EUID" -eq 0 ]]; then
    echo "❌ ERRO: Não execute este instalador como root (sudo)."
    echo "   O script pedirá a senha do sudo sozinho quando precisar."
    exit 1
fi

if ! command -v apt >/dev/null 2>&1; then
    echo "❌ ERRO: Este instalador requer uma distribuição baseada em Debian/Ubuntu (Zorin, Mint, etc)."
    exit 1
fi

echo "📦 1/6 Instalando dependências de sistema..."
sudo apt update
sudo apt install -y \
    git curl python3 python3-venv python3-pip python3-dev build-essential \
    libportaudio2 portaudio19-dev \
    libxcb-cursor0 libxcb-xinerama0

echo "🛡️ 2/6 Configurando permissões de hardware (udev + uaccess)..."
sudo tee /etc/udev/rules.d/99-baseus-presenter.rules > /dev/null <<'EOF'
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", TAG+="uaccess"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "📥 3/6 Baixando o projeto (branch: $BRANCH)..."
TMP_CLONE=$(mktemp -d)
git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TMP_CLONE"

mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/app"
cp -r "$TMP_CLONE/app" "$INSTALL_DIR/"

# Copiando TODOS os arquivos raiz vitais para a instalação final
cp "$TMP_CLONE/baseus_app.py" \
   "$TMP_CLONE/requirements.txt" \
   "$TMP_CLONE/version" \
   "$TMP_CLONE/updater.sh" \
   "$INSTALL_DIR/"

rm -rf "$TMP_CLONE"

# Garantindo permissão de execução para o atualizador
chmod +x "$INSTALL_DIR/updater.sh"

if [[ ! -f "$INSTALL_DIR/baseus_app.py" ]] || [[ ! -f "$INSTALL_DIR/version" ]]; then
    echo "❌ ERRO: download incompleto — baseus_app.py ou version ausentes em $INSTALL_DIR."
    exit 1
fi

echo "🐍 4/6 Criando ambiente virtual e instalando dependências Python..."
if [[ -d "$INSTALL_DIR/.venv" ]]; then
    echo "♻️  Ambiente virtual anterior encontrado — recriando do zero..."
    rm -rf "$INSTALL_DIR/.venv"
fi
python3 -m venv "$INSTALL_DIR/.venv"
PYTHON="$INSTALL_DIR/.venv/bin/python"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "🖥️ 5/6 Configurando lançador..."
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Baseus Presenter
Comment=Driver não-oficial para o passador Baseus Orange Dot AI
Exec="$PYTHON" "$INSTALL_DIR/baseus_app.py"
Path=$INSTALL_DIR
Icon=input-tablet
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
chmod +x "$DESKTOP_DIR/$DESKTOP_FILE"

rm -f "$AUTOSTART_DIR/$DESKTOP_FILE"

if [[ "$ENABLE_AUTOSTART" == "true" ]]; then
    mkdir -p "$AUTOSTART_DIR"
    cp "$DESKTOP_DIR/$DESKTOP_FILE" "$AUTOSTART_DIR/$DESKTOP_FILE"
    echo "✓ Inicialização automática ativada."
else
    echo "✓ Inicialização automática desativada (use o menu de aplicativos pra abrir)."
fi

echo ""
echo "✅ 6/6 INSTALAÇÃO CONCLUÍDA!"
echo ""
echo "🔌 Desconecte e conecte o passador Baseus de novo pra aplicar as permissões."
echo "   Não precisa reiniciar o computador nem fazer logout."