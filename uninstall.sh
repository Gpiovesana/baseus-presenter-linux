#!/bin/bash
set -euo pipefail

echo "🗑️ Iniciando a desinstalação do Baseus Presenter..."

echo "1/4 Removendo regras do Kernel (udev)..."
if [ -f /etc/udev/rules.d/99-baseus.rules ]; then
    sudo rm /etc/udev/rules.d/99-baseus.rules
    sudo udevadm control --reload-rules && sudo udevadm trigger
fi

echo "2/4 Removendo grupo de segurança..."
if getent group baseus > /dev/null 2>&1; then
    sudo gpasswd -d $USER baseus || true
    sudo groupdel baseus || true
fi

echo "3/4 Removendo lançador e inicialização automática..."
rm -f ~/.config/autostart/baseus-presenter.desktop
rm -f ~/.local/share/applications/baseus-presenter.desktop
rm -f ~/.config/baseus_pointer.lock

echo "4/4 Removendo arquivos do aplicativo..."
if [ -d ~/BaseusPresenter ]; then
    rm -rf ~/BaseusPresenter
fi

echo ""
echo "✅ DESINSTALAÇÃO CONCLUÍDA!"
echo "Nota: Seus arquivos de configuração em ~/.config/baseus_pointer.json"
echo "e seus modelos de voz baixados em ~/.config/baseus_pointer/models foram mantidos por segurança."
