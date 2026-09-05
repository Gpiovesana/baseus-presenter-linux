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

echo "📦 1/4 Instalando dependências do sistema..."
sudo apt update
sudo apt install -y python3-pyqt5 python3-evdev libportaudio2 portaudio19-dev python3-pip python3-venv wget

echo "🛡️ 2/4 Criando blindagem de segurança no Kernel (udev)..."
sudo groupadd -f baseus
sudo usermod -aG baseus $USER

echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abc8", GROUP="baseus", MODE="0660"' | sudo tee /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'SUBSYSTEM=="input", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'KERNEL=="uinput", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "📥 3/4 Baixando o aplicativo do GitHub..."
mkdir -p ~/BaseusPresenter
# Lembre-se de verificar se a URL abaixo é a do SEU repositório!
wget -qO ~/BaseusPresenter/baseus_app.py https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/baseus_app.py
chmod +x ~/BaseusPresenter/baseus_app.py

echo "🐍 4/4 Criando ambiente virtual seguro (venv) e instalando IA..."
python3 -m venv ~/BaseusPresenter/.venv
~/BaseusPresenter/.venv/bin/pip install vosk sounddevice pynput argostranslate

echo "✅ INSTALAÇÃO CONCLUÍDA!"
echo "⚠️ ATENÇÃO: Reinicie o computador agora para que o sistema reconheça o passador!"
