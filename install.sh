#!/bin/bash
set -euo pipefail

echo "🚀 Iniciando a instalação do Baseus Presenter..."

if [[ "$EUID" -eq 0 ]]; then
    echo "❌ ERRO: Não execute este instalador como root (sudo)."
    echo "O script pedirá a senha do sudo automaticamente quando for necessário."
    exit 1
fi

if ! command -v apt >/dev/null; then
    echo "❌ ERRO: Este instalador requer uma distribuição baseada em Debian/Ubuntu (Zorin, Mint, etc)."
    exit 1
fi

echo "📦 1/5 Instalando dependências do sistema..."
# python3-pyudev foi adicionado aqui — sem ele o app quebra na primeira linha (import pyudev)
sudo apt update
sudo apt install -y python3-pyqt5 python3-evdev python3-pyudev libportaudio2 portaudio19-dev python3-pip python3-venv wget

echo "🛡️ 2/5 Criando blindagem de segurança no Kernel (udev)..."
sudo groupadd -f baseus
sudo usermod -aG baseus $USER

echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abc8", GROUP="baseus", MODE="0660"' | sudo tee /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'SUBSYSTEM=="input", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'KERNEL=="uinput", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "📥 3/5 Baixando o aplicativo do GitHub..."
mkdir -p ~/BaseusPresenter
# Lembre-se de verificar se a URL abaixo é a do SEU repositório!
wget -qO ~/BaseusPresenter/baseus_app.py https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/baseus_app.py
chmod +x ~/BaseusPresenter/baseus_app.py

echo "🐍 4/5 Criando ambiente virtual (venv) e instalando IA..."
# --system-site-packages é ESSENCIAL: sem isso, a venv não enxerga o PyQt5/evdev/pyudev
# instalados via apt acima, e nenhum python na máquina teria as duas listas de dependência
# ao mesmo tempo (a do apt e a do pip).
python3 -m venv --system-site-packages ~/BaseusPresenter/.venv
~/BaseusPresenter/.venv/bin/pip install --upgrade pip
~/BaseusPresenter/.venv/bin/pip install vosk sounddevice pynput argostranslate

echo "🖥️ 5/5 Configurando lançador e inicialização automática..."
cat > ~/BaseusPresenter/run.sh << EOF
#!/bin/bash
exec "\$HOME/BaseusPresenter/.venv/bin/python" "\$HOME/BaseusPresenter/baseus_app.py"
EOF
chmod +x ~/BaseusPresenter/run.sh

mkdir -p ~/.config/autostart
cat > ~/.config/autostart/baseus-presenter.desktop << EOF
[Desktop Entry]
Type=Application
Name=Baseus Presenter
Comment=Driver não-oficial para o passador Baseus Orange Dot AI
Exec=$HOME/BaseusPresenter/run.sh
Icon=input-tablet
X-GNOME-Autostart-enabled=true
Terminal=false
EOF

# Também cria a entrada no menu de aplicativos, pra poder abrir manualmente
mkdir -p ~/.local/share/applications
cp ~/.config/autostart/baseus-presenter.desktop ~/.local/share/applications/baseus-presenter.desktop

echo ""
echo "✅ INSTALAÇÃO CONCLUÍDA!"
echo ""
echo "⚠️ ATENÇÃO: Reinicie o computador (ou faça logout/login) para que:"
echo "   1. As permissões do grupo 'baseus' entrem em vigor no seu usuário"
echo "   2. O Baseus Presenter suba automaticamente no próximo login"
echo ""
echo "Se quiser rodar agora mesmo sem reiniciar (pode falhar por permissão até o login novo):"
echo "   ~/BaseusPresenter/run.sh"
