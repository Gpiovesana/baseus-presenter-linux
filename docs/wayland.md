# Wayland — integração experimental em 2026-10-15

O checkout agora seleciona `WaylandOverlay` na sessão Wayland. Ele envia
estado por QtDBus para uma extensão **GNOME 46**, que lê o cursor e desenha
atores não reativos. X11 continua usando `app/overlay.py`. A extensão foi
precedida de um spike confirmado sobre Okular em apresentação e em duas telas;
Gabriel confirmou funcionamento dos efeitos e do fullscreen do Manim em
15/10/2026; a matriz completa de encerramento, hotplug e escala mista ainda
precisa de validação. KDE/wlroots não são
atendidos por essa extensão.

## Preparação automática

Ao abrir Baseus numa sessão GNOME 46 Wayland, o aplicativo instala/atualiza
os quatro arquivos da extensão e solicita sua habilitação no usuário.
A instalação respeita `XDG_DATA_HOME` (padrão `~/.local/share`), conserva
backup e não modifica as outras extensões habilitadas. Não requer sudo.

Quando os arquivos mudam, o aviso pede salvar trabalho e sair/entrar na
sessão. Reabrir somente o aplicativo na mesma sessão não remove esse aviso:
os módulos antigos podem continuar carregados. Nenhum logout é executado.
Na sessão seguinte, abrir o Baseus conclui a habilitação. Caso o usuário tenha
desativado globalmente extensões GNOME, será necessário reativá-las nas
preferências do GNOME; o Baseus não altera essa preferência global.

Outros compositores/versões recebem aviso de incompatibilidade. Se falhar a
preparação ou conexão, a navegação de slides continua disponível. Não há
fallback automático para overlay Qt/XWayland. Não force `QT_QPA_PLATFORM`.

Para reparo manual, dentro da instalação:

```bash
.venv/bin/python -m app.gnome_extension
```

Esse comando apenas instala e guarda backup. Depois de sair/entrar na sessão:

```bash
gnome-extensions enable baseus-presenter@baseus.local
.venv/bin/python baseus_app.py
```

Para ensaio sem passador/áudio, com Baseus fechado e PDF pronto, executar:

```bash
sleep 10
.venv/bin/python tools/wayland_overlay_smoke.py --seconds 60
```

Seis fases de10s: laser, lupa, spotlight, caneta seguindo mouse, legenda com
borracha, preto. O processo encerra sozinho. Em cada fase, observar as duas
telas, cliques e setas no Okular. O teste do passador vem depois desse ensaio.
Uma falha do cliente/desconexão limpa o desenho; lease de4s também cobre cliente
travado. A extensão segue habilitada e sem desenho ao encerrar o aplicativo.

```bash
gnome-extensions disable baseus-presenter@baseus.local
```

Esse comando reverte a execução da extensão. Os arquivos estão em
`~/.local/share/gnome-shell/extensions/baseus-presenter@baseus.local/`;
desabilitar antes de removê-los. Não é preciso remover configurações do Baseus.

## Contrato e limites atuais

- D-Bus de sessão: `org.gnome.Shell`, caminho
  `/org/gnome/Shell/Extensions/BaseusPresenter`, interface
  `org.gnome.Shell.Extensions.BaseusPresenter1`. Estado completo JSON limitado
  e validado; dono único por conexão, heartbeat1s, lease4s.
- Laser/spotlight/legendas/preto ficam no monitor atual. Caneta segmenta ao
  atravessar telas e preserva traços anteriores. Layout alterado limpa traços.
- Caneta limitada a500 segmentos/2000 pontos por segmento e orçamento lógico
  de8 milhões de pixels de superfícies. Segmentos antigos são descartados se
  exceder limites. Texturas finalizadas não são repintadas a cada frame.
- Spotlight move quatro painéis e um recorte circular cacheado, sem repintar
  um monitor inteiro em cada amostra do cursor.
- Lupa2x experimental (extensão v2) clona `Main.uiGroup`, com a própria lente
  como irmã desse grupo no stage, seguindo a organização da lupa nativa GNOME.
  A lente fica fora da fonte, evitando recursão. Inclui interface do Shell e
  traços de caneta. Na v1 o clone de `global.window_group` ficou preto em formas
  quadrada e circular: esse grupo declara tamanho natural zero no Mutter46.2.
  O funcionamento da lupa foi confirmado por Gabriel após recarregar a extensão.
- Timers de limpeza não protegem contra bloqueio do loop ou falha nativa do
  próprio Shell. Enquanto há efeitos/legendas/traços, o renderer inibe unredirection pela
  API do Mutter46 e libera ao remover os visuais ou resetar. Isso resolveu
  o fullscreen do Manim no teste de Gabriel. Kernel e drivers não foram alterados.

Verificações de desenvolvimento:

```bash
node tests/check_gnome_overlay.cjs
dbus-run-session -- .venv/bin/python tests/fixtures/check_overlay_dbus.py
```

Essas verificações cobrem contrato/lifecycle/transporte. Não substituem GJS e
compositor reais. Nenhuma versão/release foi publicada nesta etapa.

## Histórico da investigação (estados anteriores)

As seções abaixo preservam os testes anteriores, inclusive falhas dos probes
Qt e resultados do portal; não descrevem todas a implementação atual.

## Ambiente observado

Consulta real sem abrir overlay ou capturar pixels: Zorin/GNOME, sessão **X11**,
Qt carregado **xcb**, Qt runtime 5.15.19, PyQt 5.15.11. GNOME Shell instalado
46.0; mutter-common 46.2; xdg-desktop-portal 1.18.4, backend GNOME 46.2.
Os números dos pacotes identificam a instalação; não comprovam a versão de um
processo de compositor que ainda não foi reiniciado depois de uma atualização.

Monitores: HDMI-A-0, geometria `(0,538,1600,900)`, DPR 1;
DisplayPort-0, `(1600,0,1920,1080)`, DPR 1. Não há evidência de escala mista.
Amostra de cursor Qt obtida; uma amostra não valida rastreamento global.
A conexão XCB exigiu acesso à sessão fora do sandbox; uma falha de conexão
no sandbox não representa falha do aplicativo no compositor.

| Recurso | X11/XCB nesta execução | GNOME Wayland | KDE Wayland |
|---|---|---|---|
| Backend e monitores | consultados com sucesso | Carregou, mas isolado | não disponível |
| Acima de apresentação fullscreen | não testado | Sucesso (visível por cima) | não testado |
| Clique atravessando/foco | não testado | Falha (bloqueia mouse e teclado) | não testado |
| Cursor global e troca de monitor | não testado | Falha (preso, não atualiza globalmente) | não testado |
| Escala mista/hotplug | não testado | não testado | não testado |
| Portal: permissão, cancelamento, revogação | capacidades consultadas; captura não testada | autorização usada no teste de Gabriel; cancelamento/revogação pendentes | não testado |
| Frames PipeWire, latência, autocaptura | não testado | imagem dos slides confirmada por Gabriel; latência/autocaptura pendentes | não testado |

**Observações GNOME Wayland (Gabriel):** no protótipo nativo testado,
o cursor não acompanhou globalmente, a lupa ficou preta e cliques/atalhos não
chegaram como esperado à apresentação. Isso reprova aquela configuração do
protótipo; não demonstra que o protocolo Wayland proíba click-through. A região
de entrada, o foco, o empilhamento e a fonte de cursor precisam ser investigados
separadamente. A causa exata no compositor ainda não foi estabelecida.

Com Baseus forçado a xcb em Wayland, Gabriel relatou rastreamento parcial fora
da apresentação, lupa preta e ausência de troca de monitor. Com Okular forçado
a xcb, quase tudo funcionou em um monitor exceto a lupa; com Okular forçado a
wayland, as ferramentas visuais travaram e o pincel parou, mas as teclas de
avanço/retorno continuaram funcionando. Os backends do Okular foram solicitados
por variável de ambiente, sem log que confirme qual plugin foi carregado.

## Reprodução do protótipo Qt

Na raiz do repositório, em um terminal da sessão em avaliação:

```bash
.venv/bin/python tools/wayland_probe/probe.py --backend wayland --output /tmp/baseus-native.json
.venv/bin/python tools/wayland_probe/probe.py --backend wayland --overlay --seconds 60 --output /tmp/baseus-native-overlay.json
```

Para a referência X11 ou comparação XWayland, use `--backend xcb`. O relatório
classifica **XWayland** somente quando a sessão é Wayland e o Qt realmente
carregou xcb. Sessão desconhecida com xcb continua `unknown`. Não ocorre fallback
intencional para X11. Se Qt abortar antes de criar a aplicação, preserve stderr;
nenhum JSON de sucesso é produzido. `--backend offscreen` serve apenas ao smoke
test da ferramenta, nunca à comprovação de capacidades do desktop.

O modo overlay cria uma superfície transparente por monitor, com borda magenta,
marcador do cursor Qt, flags de clique atravessando e ausência de foco. Encerra
sozinho. Durante os 60 segundos:

1. Abra a apresentação fullscreen antes do comando e confira a borda/marcador.
2. Clique no slide sob a borda e use atalhos da apresentação; confira avanço e foco.
3. Mova o cursor entre monitores, inclusive bordas e coordenadas negativas.
4. Repita com escalas diferentes, depois com conexão/desconexão de um monitor.
5. Registre funciona/falha/não testado em `manual_results`, com observação,
   ambiente e aplicativo de apresentação. Os campos nunca são aprovados pelo
   script apenas porque a flag foi aceita ou `focusWindow()` ficou vazio.

A posição usada é `QCursor.pos()`: é uma **fonte candidata em avaliação**, não
uma implementação de cursor global Wayland. Falhar aqui não prova que uma
integração específica do desktop seja impossível. O protótipo Qt não implementa
layer-shell nem extensão GNOME.

## Captura autorizada

Protótipo separado, executado com Python do sistema e introspecção Gio/GStreamer:

```bash
/usr/bin/python3 tools/wayland_probe/portal_capture.py --seconds 30 --output /tmp/baseus-capture.json
/usr/bin/python3 tools/wayland_probe/portal_capture.py --preview --seconds 30 --output /tmp/baseus-preview.json
```

Requer `python3-gi`, `gir1.2-gstreamer-1.0`, elementos GStreamer e
`gstreamer1.0-pipewire` no ambiente de teste. Não são novas dependências do
aplicativo ou de seu instalador. A ferramenta pede autorização no portal,
cria sessão efêmera, seleciona monitores, recebe o descritor PipeWire e conta
frames. Não grava pixels nem persiste autorização. Fecha pipelines, descritores
e sessão ao terminar. O código do protótipo foi verificado por sintaxe e CLI;
Gabriel confirmou visualmente slides do Okular nativo em fullscreen na prévia.
Esse relato valida a imagem daquele teste; encerramento, latência e autocaptura
ainda exigem verificação própria.

Execute separadamente: cancelar no seletor; autorizar; encerrar pelo indicador
do desktop; desconectar monitor; e interromper com Ctrl+C. Confirme que o
indicador de compartilhamento desaparece após cada encerramento. O relatório
registra respostas e evento `Closed`, além de falhas de pipeline. Preview ajuda
a ver se a borda magenta entra na própria captura; deixe-o fora do monitor
capturado para distinguir a captura do overlay da recursão do preview.

`first_frame_after_authorization_ms` mede apenas a espera entre autorização e
primeiro frame. **Não é latência ponta a ponta**. Esta requer uma referência
visual sincronizada (contador no monitor e no preview, ou vídeo externo),
registrando método e amostras. Cancelamento não é aprovação de captura; zero
frames não comprova funcionamento. IDs de nó PipeWire são usados apenas nesta
sessão curta, sem reconexão automática após EOS, erro ou `Closed`.

## Decisão e fontes

Adiar as etapas 4 e 5 até obter resultados em GNOME Wayland. Qt aceita flags que
o compositor pode limitar; a janela não constitui evidência suficiente.
Layer-shell é uma alternativa para desktops que o suportam; GNOME precisa de
investigação própria. Não extrapolar resultados entre compositores.

- [Qt 5 QGuiApplication::platformName](https://doc.qt.io/archives/qt-5.15/qguiapplication.html#platformName-prop): informa o plugin efetivamente carregado.
- [Wayland wl_surface.set_input_region](https://wayland.freedesktop.org/docs/html/apa.html#protocol-spec-wl_surface-request-set_input_region): região de entrada é distinta do empilhamento da superfície.
- [gtk-layer-shell, desktops suportados](https://github.com/wmww/gtk-layer-shell#supported-desktops): suporte depende do compositor; não oferece suporte GNOME.
- [Portal ScreenCast](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html): ciclo CreateSession/SelectSources/Start/OpenPipeWireRemote, cancelamento e encerramento; versões recentes recomendam serial PipeWire para conexões duradouras.

Próxima evidência necessária: testar o leitor de cursor na máquina em **GNOME
Wayland**, por fase e monitor, antes de escolher uma integração de produção.

## Protótipo de cursor por metadados (seguimento)

Gabriel relatou captura bem-sucedida dos slides do Okular nativo em fullscreen
pelo portal. Isso valida o caminho visual naquele teste, não latência, cursor
ou integração da lupa. Também relatou diferenças entre Okular forçado a xcb
(rastreamento/desenho em um monitor, lupa preta) e nativo (ferramentas visuais
travadas). Os backends foram solicitados por ambiente, sem log do Qt do Okular.

O novo teste é independente do overlay de produção:

```bash
bash tools/wayland_probe/test_cursor.sh
```

O wrapper compila `cursor_reader.c` numa pasta temporária e a remove ao sair.
Usa cabeçalhos de desenvolvimento instalados via pkg-config ou os pacotes
extraídos em `/tmp/baseus-pipewire-dev` nesta sessão (estes desaparecem quando
/tmp for limpo). Não instala pacotes. O leitor recebe apenas o descritor
PipeWire autorizado pelo portal, solicita `SPA_META_Cursor` e não lê/salva
pixels ou bitmap do ponteiro. Exige que `AvailableCursorModes` anuncie Metadata;
caso contrário, encerra explicitamente, sem substituir por cursor embutido.

Feche o Baseus, deixe o Okular **nativo** pronto e selecione os dois monitores
no seletor, se disponível. Durante os 60 segundos após autorização, mova o
cursor em janela, na apresentação fullscreen e entre monitores. Não aparece
preview ou marcador: isso evita que uma janela de teste altere o foco.
O relatório fica em `/tmp/baseus-cursor.json`, com logs por stream ao lado.
Cada log contém timestamps monotônicos e coordenadas locais do stream, a no
máximo dez amostras por segundo; contadores incluem todos os buffers recebidos.
Não se deduzem coordenadas globais: dimensões/posição do stream são preservadas
no relatório, mas escalas, transformações e offsets precisam de validação.

Zero posições pode significar ausência de metadados, cursor inválido/parado,
falha de negociação ou ausência de frames. O relatório separa essas condições.
`id=0` significa ausência de novos dados válidos; não é interpretado como `(0,0)`.
Posições distintas no resumo não provam continuidade em fullscreen: comparar
os timestamps com as fases do teste. Encerramento precoce/erro do leitor também
é reportado, não contado como sucesso. Os testes locais usaram SPA buffers
sintéticos; a disponibilidade real no GNOME ainda depende deste teste manual.

Referências: [ScreenCast cursor modes](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html),
[PipeWire cursor metadata](https://docs.pipewire.org/structspa__meta__cursor.html).


## Retomada de 25/09: condições para o teste decisivo

A sessão observada pelo Codex está em X11. A consulta somente leitura ao portal
retornou ScreenCast versão 5, AvailableSourceTypes=7 e AvailableCursorModes=7
(inclui Metadata). Isso é anúncio de capacidade na sessão atual, não prova de
rastreamento em Wayland. O teste real abaixo continua pendente.

No código upstream do [Mutter 46.2](https://raw.githubusercontent.com/GNOME/mutter/46.2/src/backends/meta-screen-cast-monitor-stream-src.c),
`meta_screen_cast_monitor_stream_src_set_cursor_metadata` omite metadados se o
ponteiro estiver oculto ou fora do monitor compartilhado. Para um ponteiro visível,
subtrai a origem do monitor e aplica a escala da view. É evidência de implementação
upstream; não é uma medição do pacote Zorin nem uma garantia de funcionamento em
fullscreen. Mover o mouse continuamente durante cada fase reduz a interferência
da ocultação automática do cursor no Okular. Ausência após ficar parado não basta
para concluir que o rastreamento travou.

Para tornar o resultado interpretável, prefira três capturas separadas. Na sessão
Wayland, com Baseus fechado, Okular nativo pronto e ambos os monitores autorizados:

1. **Janela, 30s:** mova o mouse sobre o documento no primeiro monitor.
2. **Apresentação, 30s:** coloque o Okular em apresentação, retorne a ela após
   autorizar a captura e mova o mouse continuamente sobre os slides.
3. **Dois monitores, 60s:** alterne o ponteiro entre eles repetidamente, passando
   também sobre a apresentação. Registre se o seletor permitiu compartilhar ambos.

Execute um comando por fase, na raiz do projeto:

```bash
bash tools/wayland_probe/test_cursor.sh --seconds 30 --output "$HOME/.cache/baseus-wayland-probe/janela.json"
bash tools/wayland_probe/test_cursor.sh --seconds 30 --output "$HOME/.cache/baseus-wayland-probe/fullscreen.json"
bash tools/wayland_probe/test_cursor.sh --seconds 60 --output "$HOME/.cache/baseus-wayland-probe/monitores.json"
```

Esses relatórios e logs de coordenadas ficam fora de /tmp para sobreviverem ao
reinício. Não contêm pixels. Os cabeçalhos usados para compilar ainda estão em
/tmp/baseus-pipewire-dev e precisam ser preparados novamente se /tmp for limpo.
Não repetir um teste antes de analisar o erro da tentativa anterior.

Critério para prosseguir: vídeo negociado, metadados válidos com coordenadas
variando durante o movimento em cada fase e em cada stream autorizado. Conferir
os timestamps depois do retorno à apresentação, pois o seletor/terminal muda o
foco no início. Falha num stream não deve ser mascarada pelo sucesso em outro.
Isso ainda não valida desenho acima da apresentação, click-through, atraso do
overlay, lupa ou troca de monitor do aplicativo.

Verificação local de 25/09: leitor C e fixture compilados com avisos tratados como
erros; fixture sintética e 3 testes Python passaram. Suíte completa fora do sandbox:
273 testes em 25.637s, OK; checagem dos 26 sinais Qt passou. A importação de
sounddevice travou sob as restrições do sandbox e concluiu com ALSA default null.
Esse ajuste é do ambiente de teste, sem mudança de produção. O aborto histórico
de 21/09 não pôde ser reanalisado porque o log temporário desapareceu.

## Cursor real validado em27/09 — Okular em janela

Após recuperar cabeçalhos temporários, quatro capturas isolaram duas falhas do protótipo:

- Encerramento SIGTERM atingia threads PipeWire sem máscara herdada e perdia estatísticas. Registro de sinais movido para antes de pw_context_new. Regressão executa binário real com socketpair sem compositor; falhou com-15 antes e passou depois, incluindo stats. Sandbox produz falha de conexão nesse teste, portanto validação definitiva foi fora dele.
- Limite de metadados256x256 não intersectava o bloco fixo384x384 do Mutter46.2. Fixture C usa spa_pod_filter real contra oferta384x384; falhou antes e passou após ampliar limite. Não lê pixels nem imagem do cursor. Referência: https://raw.githubusercontent.com/GNOME/mutter/46.2/src/backends/meta-screen-cast-stream-src.c (on_stream_param_changed).

Resultados persistentes em `/home/gabriel/.cache/baseus-wayland-probe/`:
1. `20260927-212304-okular-janela`:30s; só format, saída-15; sem stats, zeros do resumo não comprovam zero buffers.
2. `20260927-212517-okular-debug`:15s; logs mostraram stream running; saída-15 sem stats.
3. `20260927-212730-okular-shutdown-fix`:saída0,819 buffers,0 metadados cursor; comprovou recepção sem negociação do bloco.
4. `20260927-212912-okular-metadata-fix`:15.170s, status ended, saída0,811 buffers com bloco cursor,504 válidos,93 amostras,88 posições distintas, stderr vazio. Monitor1600x900, origem lógica[0,385], node81, GNOME/Zorin Wayland. Coordenadas são relativas ao stream, não globais.

Journal kernel desde21:23 sem novos ring timeout/GPU reset/GPU fault/device wedged na consulta após capturas. Não conclui estabilidade duradoura. ZapZap continua sob observação com carga adicional.

Arquivos alterados nesta etapa: tools/wayland_probe/cursor_reader.c, tests/fixtures/cursor-reader-test.c, novo tests/fixtures/cursor-reader-signal-test.py, docs/wayland.md. Mudanças preexistentes preservadas; sem commit/publicação ou alterações no overlay de produção.

Verificação: compilação cc -std=gnu11 -Wall -Wextra -Werror; fixture C aprovada, regressão SIGTERM aprovada fora sandbox,4 testes Python (tests.test_cursor_probe e tests.test_wayland_probe) aprovados, git diff --check sem erros. Suíte completa do aplicativo não repetida nesta alteração isolada do protótipo.

Próxima etapa: Gabriel colocar Okular em apresentação; captura separada30s no mesmo monitor, mover mouse continuamente. Depois múltiplos monitores. Não validado ainda: backend nativo do Okular nesta execução (não inspecionado),fullscreen,multimonitor,latência,overlay acima de slides,clique atravessando ou lupa. Não confundir sucesso do consumidor de metadados com suporte completo do aplicativo Wayland.


## Flameshot no GNOME Wayland — 28/09

Gabriel forneceu captura da documentação Flameshot mostrando três rotas: permissão screenshot via `flatpak permission-set`, seleção vazia do launcher/portal e workaround `QT_QPA_PLATFORM=wayland flameshot gui` para atalho GNOME.

Estado local confirmado somente leitura: GNOME/Zorin Wayland; Flameshot `12.1.0-2build2`, Qt5.15.12, instalado por APT em `/usr/bin/flameshot`; não aparece Flatpak e não havia processo flameshot ativo na consulta. Portanto o comando Flatpak pode não ser o ajuste certo; aplicação não pertence ao sandbox Flatpak. Documentação oficial diz que a permissão portal pode ser concedida para qualquer método de instalação, então ainda não descartamos estado de permissão. Nada foi alterado.

Issue do próprio Flameshot com GNOME46/Ubuntu24.04 descreve erro semelhante e aponta XWayland versus plataforma Qt Wayland, mas é relato de usuário, não confirmação da causa desta máquina. Workaround oficial temporário: `QT_QPA_PLATFORM=wayland flameshot gui`. Próximo teste reversível, sem editar launcher/config: Gabriel executa esse comando uma vez e informa se portal pede autorização, se seletor abre e se salva captura. Só alterar atalho permanente depois de teste aprovado.

Relação com Baseus: o leitor Baseus confirmou captura `ScreenCast` e metadados PipeWire; Flameshot usa portal `Screenshot`. São interfaces diferentes do portal e o sucesso de uma não valida a outra. Se o teste Flameshot falhar, registrar erro e inspecionar logs D-Bus/portal antes de usar como evidência para arquitetura da lupa. A informação útil ao Baseus é garantir que o backend Qt nativo Wayland e associação de janela/app id estejam corretos antes de solicitar portal, além de manter ScreenCast separado de Screenshot.

Fontes: [guia oficial Wayland Flameshot](https://flameshot.org/docs/guide/wayland-help/), [issue sobre Qt Wayland com instalação APT](https://github.com/flameshot-org/flameshot/issues/4459), [documentação GNOME de captura](https://help.gnome.org/gnome-help/screen-shot-record.html.pt).
