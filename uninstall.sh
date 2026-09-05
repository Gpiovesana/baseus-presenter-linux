#!/bin/bash
set -euo pipefail

echo "🗑️ Iniciando a desinstalação do Baseus Presenter..."

echo "1/3 Removendo regras do Kernel (udev)..."
if [ -f /etc/udev/rules.d/99-baseus.rules ]; then
    sudo rm /etc/udev/rules.d/99-baseus.rules
    sudo udevadm control --reload-rules && sudo udevadm trigger
fi

echo "2/3 Removendo grupo de segurança..."
if getent group baseus > /dev/null 2>&1; then
    sudo gpasswd -d $USER baseus || true
    sudo groupdel baseus || true
fi

echo "3/3 Removendo arquivos do aplicativo..."
if [ -d ~/BaseusPresenter ]; then
    rm -rf ~/BaseusPresenter
fi

echo "✅ DESINSTALAÇÃO CONCLUÍDA!"
echo "Nota: Seus arquivos de configuração em ~/.config/baseus_pointer.json"
echo "e seus modelos de voz baixados foram mantidos por segurança."
