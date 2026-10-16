# Integração da GUI aprovada

Objetivo: substituir a apresentação da MainWindow pelas quatro telas aprovadas em docs/ui, preservando configuração, sinais, diálogos e operações reais. Execução local autorizada por Gabriel após aprovação das quatro prévias; sem agentes adicionais ou publicação.

- [x] Regressões antes de alterar produção: navegação sem gravação, bateria real comum, perfis e efeitos sincronizados, callbacks de áudio e manutenção, inglês nos novos menus.
- [x] Manter atributos/métodos de MainWindow e todos os sinais atuais. Separar composição visual em app/gui_layout.py e desenhos locais em app/gui_visuals.py. Não importar tools/ em produção.
- [x] Reutilizar os widgets reais e limites existentes; ler dispositivos/modelos/idiomas pelo código atual, sem itens de exemplo. Inicializar bateria como aguardando. Não implementar remapeamento, dispositivos extras, 3D ou backend Wayland.
- [x] Conectar a demonstração local aos ajustes existentes sem captura de tela. Layouts com rolagem; idioma e fechamento globais, legendas por perfil, pasta global.
- [x] Traduzir novas strings e compilar catálogos; ajustar teste que dependia das antigas abas para verificar navegação.
- [x] Executar testes focados, suíte completa, inspeção visual em português/inglês e tamanho reduzido. Atualizar Obsidian com resultados e limites; não abrir hardware/áudio real automaticamente.

Validação: 279 testes aprovados; 27 sinais conferidos; screenshots PT/EN e tamanho reduzido inspecionados. Hardware físico e sessão gráfica real com todas as funcionalidades não validados nesta integração.
