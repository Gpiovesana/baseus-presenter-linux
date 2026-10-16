# Plano de ação: estabilidade e Wayland

Data: 2026-09-21. Estado: proposta; implementação não iniciada.

## Objetivo e limites

Fechar as lacunas do atualizador e investigar uma implementação de overlay
Wayland preservando o funcionamento X11. Este é um roteiro por entregas;
o plano de implementação do backend depende dos resultados dos protótipos.
Não pressupõe suporte completo a GNOME, KDE ou wlroots.

Base verificada: branch dev, sem alterações rastreadas antes deste documento;
graphify-out/ não rastreado. O instalador configura apt/udev; updater.sh prepara
uma nova venv e instala requirements.txt, mas não reaplica apt/udev.
O overlay utiliza cursor global, posicionamento de janela e grabWindow(0).

## Ordem das entregas

### 1. Compatibilidade de requisitos de sistema na atualização

Arquivos envolvidos: install.sh, updater.sh, app/updater.py, testes de instalador
e updater. Criar um manifesto versionado de requisitos junto da release e um
registro do que o instalador aplicou, associado à instalação.

- [ ] Definir semântica de compatibilidade e transição para instalações antigas.
- [ ] Criar regressões para estado compatível, ausente, corrompido e incompatível;
      confirmar falha antes de implementar o comportamento.
- [ ] Registrar o estado somente após a instalação correspondente ter sucesso.
- [ ] Validar os requisitos da release antes de substituir a instalação ativa.
      Em incompatibilidade, preservar a versão funcional e orientar reinstalação.
- [ ] Garantir que ausência de registro não seja considerada compatibilidade
      comprovada; fornecer caminho explícito para instalação legada.
- [ ] Testar falha de instalação, rollback e atualização iniciada pelo updater
      antigo: o novo preflight não protege retroativamente um updater já instalado.

Conclusão: atualização incompatível não substitui a instalação ativa no fluxo
novo. Publicar primeiro uma versão preparatória com a proteção, sem alterar
requisitos de sistema; planejar separadamente a transição de clientes antigos.
O registro comprova o procedimento aplicado, não a saúde atual das permissões.

### 2. Cache e espera do verificador de atualização

Arquivos: app/updater.py, app/config.py se necessário, tests/test_gui_update.py
e novo teste específico do cache.

- [ ] Criar testes com relógio e respostas HTTP simulados: reinício dentro do
      intervalo, cache vencido, sem rede, limite HTTP e solicitação manual.
- [ ] Persistir resultado útil e horário da última verificação bem-sucedida.
- [ ] Respeitar Retry-After e informações de limite quando presentes; evitar
      tratar todo HTTP 403 como limite de requisições.
- [ ] Permitir consulta manual sem cache, respeitando espera imposta pelo servidor.
- [ ] Preservar execução em segundo plano e mensagens claras em português/inglês.

Conclusão: reiniciar o aplicativo não provoca consultas repetidas desnecessárias;
indisponibilidade de rede não trava a interface nem é registrada como sucesso.

### 3. Protótipos Wayland isolados — antes da refatoração

Local proposto: tools/wayland_probe/; relatório em docs/wayland.md.

- [ ] Registrar sessão, desktop/compositor e versão, Qt/PyQt, backend efetivamente
      carregado e configuração dos monitores; distinguir Wayland nativo e XWayland.
- [ ] No GNOME do usuário, testar superfície acima de apresentação em tela cheia,
      clique atravessando e ausência de roubo de foco.
- [ ] Testar fonte de posição do cursor, múltiplos monitores e escalas diferentes.
- [ ] Testar captura autorizada para lupa: cancelamento, encerramento da sessão
      de captura, latência e risco de capturar o próprio overlay.
- [ ] Repetir em KDE se houver ambiente disponível, registrando resultados por
      funcionalidade. Não declarar sucesso de um compositor para outro.
- [ ] Decidir escopo: backend nativo viável, integração específica com desktop,
      suporte parcial claramente indicado ou adiamento.

Conclusão: relatório reproduzível com funciona/falha/não testado por recurso.
Falha de uma flag Qt não comprova impossibilidade no protocolo.

### 4. Separação mínima do overlay, condicionada à etapa 3

Arquivos: app/overlay.py, baseus_app.py, tests/test_overlay_render.py e novos
módulos estritamente necessários para desenho compartilhado e integração X11.

- [ ] Caracterizar comportamento X11 com testes existentes e testes adicionais
      de foco, troca de monitor e ciclo de exibição quando necessários.
- [ ] Separar desenho de captura, posicionamento e obtenção do cursor.
- [ ] Manter métodos/sinais consumidos pelo restante do aplicativo compatíveis.
- [ ] Validar X11 real após a extração, sem adicionar comportamento Wayland neste passo.

Conclusão: mesma experiência X11, sem duplicar desenho e sem novos backends fictícios.

### 5. Backend Wayland e escolha automática

Arquivos previstos: app/overlay_wayland.py e ponto de criação em baseus_app.py;
o mecanismo concreto de integração será o comprovado na etapa 3.

- [ ] Especificar capacidades antes de implementar a seleção; não escolher apenas
      por XDG_SESSION_TYPE nem assumir X11 quando a sessão for desconhecida.
- [ ] Integrar primeiro janela e recursos visuais comprovados, depois rastreamento
      do cursor e por último a lupa com captura assíncrona.
- [ ] Configurar integrações que precisem anteceder QApplication na fase correta;
      verificar o backend carregado após a inicialização.
- [ ] Indicar recursos indisponíveis com motivo claro; não prometer que XWayland
      resolve automaticamente as limitações de uma sessão Wayland.
- [ ] Testar encerramento, permissão negada/revogada e desconexão de monitor.

Conclusão: matriz de suporte comprovada, X11 preservado e degradação explícita
quando determinada funcionalidade não estiver disponível.

### 6. Melhorias independentes de manutenção e áudio

- [ ] Extrair gestão de modelos Vosk e pacotes Argos de app/gui.py, mantendo
      diálogos na UI e preservando separação entre idioma da interface e do modelo.
- [ ] Medir duração da tradução em app/audio.py antes de propor mais threads.
- [ ] Só separar reconhecimento/tradução se as medidas justificarem, incluindo
      testes de troca de sessão, ordem dos resultados e parciais obsoletos.

Estas tarefas não bloqueiam os protótipos Wayland; não misturar refatoração de
modelos com alteração de concorrência no mesmo conjunto de mudanças.

## Verificação e publicação

Para cada mudança de comportamento: teste que falha, implementação mínima,
teste que passa. Executar testes específicos durante o trabalho e
`bash tools/pre-commit` ao concluir cada entrega integrada; verificar também
`bash -n install.sh updater.sh uninstall.sh` quando alterar os scripts.

Testes offscreen e mocks não validam compositor, microfone ou passador físico.
Antes de anunciar suporte: validar no notebook e em sessão real do ambiente
anunciado. Fluxo de publicação proposto: dev, testes reais, revisão, main,
release com matriz de suporte. Push, merge e publicação dependem de autorização.

## Fontes da investigação de Wayland

- [Região de entrada no protocolo](https://wayland.freedesktop.org/docs/html/apa.html#protocol-spec-wl_surface-request-set_input_region): clique atravessando é separado de posicionamento em camadas.
- [Layer Shell e desktops suportados](https://github.com/wmww/gtk-layer-shell#supported-desktops): KDE e GNOME exigem avaliação distinta.
- [Plataforma Qt carregada](https://doc.qt.io/qt-6/qguiapplication.html#platformName-prop): sessão e backend da aplicação não são a mesma informação; verificar a implementação na versão PyQt5 usada pelo projeto.
