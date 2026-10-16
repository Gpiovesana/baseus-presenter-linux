# Overlay GNOME Wayland — integração experimental

Gabriel autorizou execução contínua em 15/10, reservando interrupções para
decisões de produto, mudanças de sistema e testes físicos. O spike Shell já
validou desenho não reativo acima de Okular fullscreen e em dois monitores.

## Contrato

Selecionar backend pela sessão: X11 conserva PointerWindow; Wayland usa um
QObject com os mesmos slots públicos, ligado à extensão GNOME 46. Nunca
forçar xcb como solução de overlay. Sem migração de configuração.

No barramento de sessão, destino org.gnome.Shell, caminho
/org/gnome/Shell/Extensions/BaseusPresenter e interface
org.gnome.Shell.Extensions.BaseusPresenter1. Update(s JSON) retorna b;
Release() encerra a sessão visual daquele remetente. Estado completo com
protocol=1, active, mode, pen, pen_serial, clear_serial, black, subtitle, visual.
Subtitles limitadas a2048 code points, payload a16384; bools e números/cor
validados antes de usar. Um único remetente por vez. Heartbeat a1s, lease4s;
Release/queda do cliente/expiração limpam visuais. Chamadas Qt assíncronas com
timeout1s e no máximo uma em andamento; sem coordenadas por D-Bus.

Extensão permanece sem desenho até receber Update. Atores não reativos,
sem modal/grabs/alterar unredirection. Laser por ator; spotlight por quatro
painéis e um recorte circular Cairo cacheado; caneta usa áreas
por traço limitadas e cacheadas quando concluídas. Limites500 traços e2000
pontos por traço, orçamento lógico8M pixels para superfícies de traços.
Mudança de monitor segmenta traços. Layout alterado limpa
traços para evitar desenhos em posições antigas. Legenda e preto no monitor
atual. Lupa2x clona Main.uiGroup; lente anexada como irmã no stage para ficar
fora da própria fonte, como na lupa nativa GNOME. Primeira tentativa com
window_group ficou preta (grupo declara tamanho natural zero). Forma
circular/retangular quando recorte disponível. Capacidade da lupa é
experimental até teste real, sem afirmar equivalência ao portal.

Extensão ausente/incompatível: GUI continua, aviso claro; nenhuma superfície
Qt bloqueadora é criada no Wayland. X11 preserva o caminho existente.
Instalação da extensão é explícita por helper local; sem ativar globalmente
ou pedir logout pelo programa. Remover cliente não deixa ator preso.

## Verificação

Testar seleção, estado/slots, lease, remetentes, entradas inválidas, cleanup e
mensagens de falha; executar suíte existente. Checagens com mocks não provam
GJS/compositor. Extensão nova pode exigir login manual. Depois testar D-Bus
real antes do hardware; validar laser/modos/borracha/legendas com passador,
Okular e dois monitores. Instabilidade GPU segue investigação separada.
