#!/usr/bin/env bash
# Disposable build and run. No packages are installed and no pixels are saved.
set -euo pipefail
PROBE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$(mktemp -d /tmp/baseus-cursor-build.XXXXXX)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT
if pkg-config --exists libpipewire-0.3 2>/dev/null; then
    # pkg-config emits compiler arguments, not shell commands.
    read -r -a COMPILE_FLAGS <<< "$(pkg-config --cflags libpipewire-0.3)"
    read -r -a LINK_FLAGS <<< "$(pkg-config --libs libpipewire-0.3)"
else
    HEADER_ROOT=/tmp/baseus-pipewire-dev/extracted/usr/include
    if [[ ! -f "$HEADER_ROOT/pipewire-0.3/pipewire/pipewire.h" ]]; then
        echo 'Cabeçalhos PipeWire não encontrados. É necessário preparar libpipewire-0.3-dev e libspa-0.2-dev para este protótipo.' >&2
        exit 1
    fi
    COMPILE_FLAGS=(-isystem "$HEADER_ROOT/pipewire-0.3" -isystem "$HEADER_ROOT/spa-0.2")
    LINK_FLAGS=(-l:libpipewire-0.3.so.0)
fi
cc -std=gnu11 -Wall -Wextra -Werror "${COMPILE_FLAGS[@]}" \
    "$PROBE_DIR/cursor_reader.c" "${LINK_FLAGS[@]}" -o "$BUILD_DIR/cursor-reader"
/usr/bin/python3 "$PROBE_DIR/portal_capture.py" --cursor-metadata \
    --cursor-reader "$BUILD_DIR/cursor-reader" --seconds 60 \
    --output /tmp/baseus-cursor.json "$@"
