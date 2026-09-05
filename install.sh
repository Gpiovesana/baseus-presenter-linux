#!/bin/bash

echo "🚀 Iniciando a instalação do Baseus Presenter (v1.1)..."

echo "📦 1/4 Instalando dependências do sistema..."
sudo apt update
sudo apt install -y python3-pyqt5 python3-evdev libportaudio2 portaudio19-dev python3-pip wget

echo "🐍 2/4 Instalando Inteligência Artificial e Áudio..."
pip install vosk sounddevice pynput argostranslate --break-system-packages

echo "🛡️ 3/4 Criando blindagem de segurança no Kernel (udev)..."
# Cria um grupo de segurança exclusivo para o aplicativo
sudo groupadd -f baseus
sudo usermod -aG baseus $USER

# Regras restritas apenas para quem pertence ao grupo 'baseus' (MODE="0660")
echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="abc8", GROUP="baseus", MODE="0660"' | sudo tee /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'SUBSYSTEM=="input", ATTRS{idVendor}=="abc8", ATTRS{idProduct}=="ca08", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
echo 'KERNEL=="uinput", GROUP="baseus", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-baseus.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "📥 4/4 Baixando o aplicativo do GitHub..."
mkdir -p ~/BaseusPresenter
# ATENÇÃO: Troque a URL abaixo pela URL 'Raw' do seu arquivo baseus_app.py no GitHub!
wget -qO ~/BaseusPresenter/baseus_app.py https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/baseus_app.py
chmod +x ~/BaseusPresenter/baseus_app.py

echo "✅ INSTALAÇÃO CONCLUÍDA!"
echo "⚠️ ATENÇÃO: Como alteramos suas permissões de segurança no Linux,"
echo "você precisa REINICIAR O COMPUTADOR agora para o sistema reconhecer o passador!"
