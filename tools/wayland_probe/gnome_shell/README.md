# Spike GNOME Shell 46 — não é backend de produção

Molduras verdes por monitor e ponto rosa seguindo o cursor por 30 segundos.
Usa `addTopChrome` com `affectsInputRegion: false`, `trackFullscreen: false`
e atores não reativos. Não solicita foco, não usa modal/grab e não altera
unredirection. O timer move apenas o ponto, sem repintar telas inteiras.

A extensão executa dentro do Shell. O timeout depende de o loop do Shell
continuar respondendo; não é proteção contra falha nativa ou bloqueio desse loop.

Copiar `metadata.json` e `extension.js` para
`~/.local/share/gnome-shell/extensions/baseus-overlay-probe@baseus.local/`.
Em seguida conferir `gnome-extensions info baseus-overlay-probe@baseus.local`.
Se desconhecida, salvar o trabalho e fazer logout/login manualmente.
Não reiniciar o Shell de uma sessão Wayland.

Com Baseus fechado e Okular em apresentação, executar (10s para voltar ao PDF):

```bash
sleep 10
gnome-extensions enable baseus-overlay-probe@baseus.local
```

Verificar visualmente molduras nas duas telas, ponto cruzando monitores,
cliques e setas avançando slides sem desaparecer a moldura. Comparar foco no log:

```bash
journalctl --user -b -o cat --grep='BASEUS-PROBE'
```

Depois do timeout os atores somem, mas a extensão permanece habilitada e inerte.
Desabilitar ao terminar; para repetir, desabilitar e habilitar novamente.

```bash
gnome-extensions disable baseus-overlay-probe@baseus.local
```

Reversão: após desabilitar, remover somente os dois arquivos da extensão e a pasta
vazia. Nenhuma configuração ou arquivo do Baseus foi migrado.

Checagem de ciclo de vida com mocks: `node tools/wayland_probe/gnome_shell/check.cjs`.
Essa checagem não valida GJS, renderização, input ou empilhamento reais.
