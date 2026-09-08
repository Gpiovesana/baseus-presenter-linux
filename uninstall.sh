#!/bin/bash
set -euo pipefail

INSTALL_DIR="$HOME/BaseusPresenter"
DESKTOP_FILE="baseus-presenter.desktop"

echo "🗑️ Iniciando a desinstalação do Baseus Presenter..."

echo "1/3 Removendo regra udev..."
if [ -f /etc/udev/rules.d/99-baseus-presenter.rules ]; then
    sudo rm /etc/udev/rules.d/99-baseus-presenter.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi
# Nota: não há grupo customizado pra remover — a versão atual usa uaccess
# (por sessão gráfica), não um grupo persistente do sistema.

echo "2/3 Removendo lançador e inicialização automática..."
rm -f "$HOME/.local/share/applications/$DESKTOP_FILE"
rm -f "$HOME/.config/autostart/$DESKTOP_FILE"

echo "3/3 Removendo arquivos do aplicativo..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
fi

echo ""
echo "✅ DESINSTALAÇÃO CONCLUÍDA!"
echo "Nota: suas configurações em ~/.config/baseus_presenter/ (incluindo"
echo "modelos de voz baixados e perfis salvos) foram mantidas por segurança —"
echo "apague essa pasta manualmente se quiser remover tudo."
