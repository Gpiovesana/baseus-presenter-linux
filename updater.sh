#!/bin/bash
set -euo pipefail

REPO="Gpiovesana/baseus-presenter-linux"
INSTALL_DIR="$HOME/BaseusPresenter"

VERSION="${1:-}"
PID="${2:-}"

if [[ -z "$VERSION" ]]; then
    echo "❌ Versão não informada."
    exit 1
fi

if [[ -z "$PID" ]]; then
    echo "❌ PID do aplicativo não informado."
    exit 1
fi

VERSION="${VERSION#v}"

echo "🔄 Atualizando Baseus Presenter para v$VERSION..."

TMP_DIR="$(mktemp -d)"
BACKUP_DIR="$INSTALL_DIR/.update-backup"
RELEASE_DIR="$TMP_DIR/release"

cleanup() {
    rm -rf "$TMP_DIR"
}

trap cleanup EXIT

mkdir -p "$RELEASE_DIR"

echo "📥 Baixando Release..."

curl -fL \
    "https://github.com/$REPO/archive/refs/tags/v$VERSION.tar.gz" \
    -o "$TMP_DIR/release.tar.gz"

echo "📦 Extraindo..."

tar -xzf "$TMP_DIR/release.tar.gz" -C "$TMP_DIR"

EXTRACTED_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"

if [[ ! -f "$EXTRACTED_DIR/baseus_app.py" ]]; then
    echo "❌ Release inválida: baseus_app.py não encontrado."
    exit 1
fi

if [[ ! -f "$EXTRACTED_DIR/requirements.txt" ]]; then
    echo "❌ Release inválida: requirements.txt não encontrado."
    exit 1
fi

if [[ ! -f "$EXTRACTED_DIR/version" ]]; then
    echo "❌ Release inválida: arquivo version não encontrado."
    exit 1
fi

echo "✓ Release validada."

# Espera o aplicativo principal terminar.
echo "⏳ Aguardando o Baseus Presenter encerrar..."

while kill -0 "$PID" 2>/dev/null; do
    sleep 0.5
done

echo "✓ Aplicativo encerrado."

# Backup da instalação atual.
rm -rf "$BACKUP_DIR"
mv "$INSTALL_DIR" "$BACKUP_DIR"

# Cria nova instalação.
mkdir -p "$INSTALL_DIR"

cp -r "$EXTRACTED_DIR/app" "$INSTALL_DIR/"
cp "$EXTRACTED_DIR/baseus_app.py" "$INSTALL_DIR/"
cp "$EXTRACTED_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$EXTRACTED_DIR/version" "$INSTALL_DIR/"

echo "🐍 Atualizando dependências..."

python3 -m venv "$INSTALL_DIR/.venv"

"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install \
    -r "$INSTALL_DIR/requirements.txt"

echo "✓ Nova versão instalada."

# Atualiza o lançador.
DESKTOP_FILE="$HOME/.local/share/applications/baseus-presenter.desktop"

PYTHON="$INSTALL_DIR/.venv/bin/python"

cat > "$DESKTOP_FILE" <<EOF
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

chmod +x "$DESKTOP_FILE"

# Atualiza o autostart somente se ele já existia.
AUTOSTART_FILE="$HOME/.config/autostart/baseus-presenter.desktop"

if [[ -f "$AUTOSTART_FILE" ]]; then
    cp "$DESKTOP_FILE" "$AUTOSTART_FILE"
fi

echo "🧹 Removendo backup da versão antiga..."

rm -rf "$BACKUP_DIR"

echo "✅ Atualização para v$VERSION concluída!"

# Inicia a nova versão.
exec "$PYTHON" "$INSTALL_DIR/baseus_app.py"
