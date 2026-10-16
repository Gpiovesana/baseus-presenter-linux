# Cursor nativo — GNOME Wayland 46

Investigação de 2026-10-15 por codex. Ambiente inspecionado: GNOME Shell 46.0,
Mutter/Meta-14 46.2-1ubuntu0.24.04.18+zorin1.

A introspecção GJS do pacote instalado confirma `set_pointer_visible()` e
`get_pointer_visible()`, mas não `inhibit_cursor_visibility()` nem
`uninhibit_cursor_visibility()`. A API de inibição foi introduzida no ciclo
[Mutter 49.alpha.1](https://github.com/GNOME/mutter/blob/49.alpha.1/NEWS).
Não usá-la incondicionalmente na extensão, que declara suporte ao GNOME 46.

Uma chamada a `set_pointer_visible(false)` não impede uma chamada posterior do
compositor de mostrar o cursor. O renderer guardava apenas o estado solicitado,
então não ocultava novamente o ponteiro depois dessa mudança externa.
A correção segue a [lupa do GNOME Shell 46](https://github.com/GNOME/gnome-shell/blob/46.0/js/ui/magnifier.js):
conecta `visibility-changed` durante os efeitos e reaplica a ocultação somente
se o ponteiro estiver visível. Desconecta antes de restaurar a visibilidade.
O `reset()` existente cobre Release, perda do cliente, expiração da sessão,
erro de renderização, mudança de monitores e `disable()` da extensão.

No teste real, Gabriel confirmou os efeitos funcionando, mas relatou cursor
piscando ao mover, exceto na tela preta. A primeira correção omitia outra parte
do padrão da lupa: `Clutter.Seat.inhibit_unfocus()`. No Mutter 46, ocultar o
cursor libera a proteção de foco mantida pelo próprio tracker; a extensão
agora mantém uma referência adicional durante os efeitos e libera exatamente
uma vez após restaurar o cursor. Ambos os métodos de foco foram confirmados
por introspecção local. Isso preserva o foco do ponteiro oculto; a eliminação
da cintilação ainda depende de novo teste visual, não é comprovada pelo teste
sintético. Não confundir essa API de foco com a API de visibilidade do Mutter49.

### Resultado real e limite confirmado

Após carregar o ajuste de foco, Gabriel relatou melhora, mas confirmou que a
seta original ainda pisca durante movimento (não se trata de saltos dos
efeitos). Consulta à sessão confirmou extensão ACTIVE, arquivos instalados
iguais ao checkout, sem erros de renderer nos logs consultados e lupa de
acessibilidade desativada. Isso não mede a frequência da cintilação.

O [relato respondido por Florian Müllner no GNOME Discourse](https://discourse.gnome.org/t/proper-way-to-hide-cursor-until-manually-un-hidden/29888)
descreve exatamente a reaparição breve com `visibility-changed`. O mantenedor
explica que os componentes disputam a visibilidade nas versões anteriores ao
GNOME49 e que acompanhar o sinal e ocultar novamente é o contorno disponível.
Trocar a forma do cursor por uma imagem transparente também disputa com os
cursores definidos pelos aplicativos; não foi adotado.

O código do Mutter46 mostra a ordem relevante: eventos de ponteiro podem chamar
`set_pointer_visible(TRUE)` em `update_pointer_visibility_from_event()`; o setter
atualiza o renderer antes de emitir `visibility-changed`. Logo, o callback JS
da extensão reage depois da atualização, sem garantia de impedir uma aparição
transitória. Testes síncronos de estado final não validam esse intervalo.

Não foi aplicado terceiro remendo nem alterado compositor/driver/sistema.
A correção atual melhora a ocultação e mantém restauração, mas **não garante
ausência de cintilação no GNOME46**. Resolver pelo mecanismo de inibição requer
um ambiente que ofereça essa API (introduzida no ciclo49), adaptação da extensão
e testes reais nesse ambiente. Atualizar o sistema está fora desta alteração.

## Verificação automatizada

```bash
python3 -m unittest discover -s tests -p test_gnome_cursor.py -v
bash tools/pre-commit
```

O teste GJS executa o renderer e o encerramento da extensão reais com um tracker
simulado que usa sinais GObject reais. Cobre reaparição externa do ponteiro,
ausência de recursão, chamadas repetidas, ativação/desativação de laser, lupa,
spotlight e tela preta, reset, ausência de monitor e disable repetido. Não
executa o compositor nem verifica pixels na tela. Sem GJS, o teste é pulado.

## Verificação visual pendente

Com a versão corrigida instalada e carregada na sessão GNOME Wayland:

1. Ativar cada efeito e mover o ponteiro sobre janelas nativas e XWayland,
   na área de trabalho e em apresentação fullscreen; procurar cursor duplicado
   ou cintilação. Repetir atravessando monitores.
2. Desativar cada efeito e confirmar que o cursor volta imediatamente.
   Alternar efeitos repetidas vezes e testar efeitos sobrepostos.
3. Com um efeito ativo, fechar normalmente o aplicativo, encerrar seu processo
   e desativar a extensão; confirmar restauração em cada caso. Testar também
   expiração da sessão e mudança de monitores.
4. Confirmar que o foco, cliques e movimento continuam funcionando enquanto
   o cursor está oculto. Não combinar com Zoom nativo nesta configuração:
   o ensaio de coexistência produziu imagem fragmentada e foi interrompido.

Os testes automatizados não demonstram ausência de cintilação nem validam o
cursor por hardware. A extensão instalada na sessão não é atualizada apenas
pela edição deste checkout; é necessário instalar e recarregar a nova versão.

## Experimento de composição no fullscreen (GNOME 46)

O renderer agora mantém uma referência de `Meta.disable_unredirect_for_display`
quando há efeitos, legendas ou traços na tela, como faz a lupa nativa do Shell46.
Libera com `enable_unredirect_for_display` ao remover o último visual e no reset/
desligamento. Isso testa a hipótese de scanout direto na apresentação Manim;
não confirma a causa nem elimina a limitação de cintilação do cursor.

Validar após recarregar a sessão: Zoom nativo desligado, laser sobre o slide
fullscreen, depois spotlight/lupa/tela preta; alternar para janela e entre
monitores; desligar efeitos, limpar desenhos e fechar Baseus. A suíte verifica
balanceamento das referências, mas não reproduz scanout nem composição real.

## Validação relatada em 15/10/2026

Gabriel confirmou efeitos no fullscreen do Manim em Wayland após a mudança
de composição, e ocultação do cursor no X11 após a integração XFixes.
A cintilação residual no GNOME46 e a incompatibilidade observada com Zoom
nativo continuam como limitações. Não generalizar estes testes a outros
compositores, versões do Shell ou configurações de monitores.
