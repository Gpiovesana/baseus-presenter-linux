# GNOME overlay integration plan

**Goal:** conectar hardware/GUI existentes a renderização no Shell em Wayland.
**Spec:** ../specs/2026-10-15-gnome-overlay.md
**Execution:** inline, autorizado por Gabriel; sem aprovações entre tarefas.
**Architecture:** QObject QtDBus envia estado; extensão GNOME valida e desenha.
**Constraints:** X11 preservado, sem GRUB/drivers/restart automático, sem
unredirection, produção não declarada pronta por testes sintéticos.

- [x] Cliente e seleção: app/overlay_wayland.py, app/overlay_backend.py,
  baseus_app.py. Testar slots existentes, perfil, expiração de legenda e
  indisponibilidade/reconexão sem bloquear GUI.
- [x] Extensão: extensions/baseus-presenter@baseus.local/{extension.js,
  renderer.js,protocol.js,metadata.json}. Testar validação, lease/owner,
  cleanup e limites antes de executar no Shell.
- [x] Instalação explícita e guia; ferramenta de smoke test sem hardware.
  Rodar suíte existente/sinais/sintaxe, revisar limites/erros.
- [x] Instalar desabilitada e conferir reconhecimento: UUID novo ainda não
  conhecido pelo Shell. Handoff para login manual registrado no vault.
- [ ] Testar serviço real/ferramentas após login e depois hardware com Gabriel.

## Ledger de execução

- 15/10: 288 testes Python em27,756s; Node valida protocol/Unicode, owner,
  lease, disconnect/release, ferramentas, gestos rápidos e cleanup.
- QtDBus real validado em barramento privado via fixture; APIs GJS/St/Clutter
  inspecionadas por GI fora do Shell. Não extrapolar para compilação/render real.
- Revisão independente encontrou pen release/press perdido por coalescência e
  divergência Unicode Python/JS; corrigidos com pen_serial e limite code points,
  regressões adicionadas. Shader corrigido para sampler declarado/unidade0.
- Ruling: manter código da extensão junto ao checkout e incluir diretório
  opcional no staging de install/updater; helper explícito instala no usuário,
  sem ativação. Evita modificar o Shell de cada usuário durante atualização.
- Ruling: lupa cria recursos apenas ao entrar em LUPA; spotlight move recorte
  cacheado em vez de redesenhar monitor inteiro. Extensão sem cliente não tem
  timer de renderização. Nenhum unredirection/grab foi introduzido.

Riscos a revisar: cliente cai com ativo/preto; payload inválido; troca de
perfil/desligamento enquanto envio em andamento; tela removida; fonte clone
e recorte da lupa; exceção no Shell. Não publicar/reiniciar automaticamente.
