#!/bin/bash
set -euo pipefail

# Ajuste aqui quando "dev" for promovida a "main" oficialmente (ver v2.0.0).
REPO_URL="https://github.com/Gpiovesana/baseus-presenter-linux.git"
BRANCH="dev"
INSTALL_DIR="$HOME/BaseusPresenter"
DESKTOP_FILE="baseus-presenter.desktop"

# --no-autostart: instala tudo normalmente, mas não sobe sozinho no login.
# O app continua acessível pelo menu de aplicativos. Funciona tanto rodando
# o script direto quanto via "wget -qO- ... | bash -s -- --no-autostart".
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
# git                -> baixar o projeto
# python3-venv/pip/dev, build-essential -> criar a venv e compilar o que não
#                       tiver wheel pronta (ex: evdev, dependendo do Python/arch)
# libportaudio2/portaudio19-dev -> runtime do sounddevice
# libxcb-cursor0/libxcb-xinerama0 -> o PyQt5 vem do pip agora (não do apt),
#                       então precisa dessas libs de sistema pro plugin
#                       gráfico xcb conseguir abrir janela. Ainda não testado
#                       em máquina limpa — se aparecer erro de "Qt platform
#                       plugin xcb" na primeira execução, é o primeiro
#                       suspeito.
sudo apt update
sudo apt install -y \
    git python3 python3-venv python3-pip python3-dev build-essential \
    libportaudio2 portaudio19-dev \
    libxcb-cursor0 libxcb-xinerama0

echo "🛡️ 2/6 Configurando permissões de hardware (udev + uaccess)..."
# uaccess (via systemd-logind) dá acesso ao dispositivo pra sessão gráfica
# ativa automaticamente, sem precisar de grupo customizado nem reboot —
# só desconectar/reconectar o passador depois da instalação já basta.
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
# Recria app/ do zero: evita arquivos órfãos se algum módulo for
# renomeado/removido numa atualização.
rm -rf "$INSTALL_DIR/app"
cp -r "$TMP_CLONE/app" "$INSTALL_DIR/"
cp "$TMP_CLONE/baseus_app.py" "$INSTALL_DIR/"
cp "$TMP_CLONE/requirements.txt" "$INSTALL_DIR/"
rm -rf "$TMP_CLONE"
# tests/ e tools/ ficam de fora de propósito: não são importados por
# baseus_app.py nem por nada em app/, servem só pra desenvolvimento.

if [[ ! -f "$INSTALL_DIR/baseus_app.py" ]] || [[ ! -f "$INSTALL_DIR/requirements.txt" ]]; then
    echo "❌ ERRO: download incompleto — baseus_app.py ou requirements.txt não apareceram em $INSTALL_DIR."
    echo "   Verifique sua conexão e tente rodar o instalador de novo."
    exit 1
fi

echo "🐍 4/6 Criando ambiente virtual e instalando dependências Python..."
# Recria do zero se já existir: uma venv de instalação anterior pode estar
# presa a uma versão de Python diferente ou a pacotes de um requirements.txt
# antigo — reinstalação deve ser previsível, não acumulativa.
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

# Exec com cada parte entre aspas: evita quebrar se $INSTALL_DIR tiver espaço
# no caminho (ex: "$HOME" incomum, ou pasta clonada com nome diferente).
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

# Remove uma entrada de autostart antiga antes de decidir de novo — cobre
# tanto quem reinstala trocando de opção quanto quem rodou sem a flag antes.
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
echo ""
echo "Pra abrir agora: procure \"Baseus Presenter\" no menu de aplicativos,"
echo "ou rode:"
echo "   $PYTHON $INSTALL_DIR/baseus_app.py"
