# Preparação para testes em outro computador

Escopo autorizado: manter na dev, sem versão nova ou publicação. Preparar automaticamente extensão GNOME46 na abertura, testar instalação/atualização em diretório temporário e verificar limpeza de cursor/efeitos no encerramento. Implementação por codex nesta sessão.

- [x] Preparação GNOME46 idempotente, respeitando XDG_DATA_HOME; outras sessões não alteradas. Ativar extensão no usuário, avisar sobre nova sessão quando arquivos mudarem ou extensão não for descoberta. Falhas não impedem navegação de slides. Testar incompatibilidade, bibliotecas/comandos ausentes e preservação de outras extensões.
- [x] Fixtures de instalação/atualização devem transportar módulos e extensão reais. Executar scripts em instalação isolada, sem sudo/rede reais, testar sucesso e rollback. Dependências X11 explicitadas no instalador.
- [x] Verificar close com ferramentas ativas, liberação D-Bus e restauração após perda/expiração de cliente; documentar o limite de verificação sintética e roteiro para máquina real.
- [x] Rodar suíte completa, revisar diff e registrar contexto. Sem alterar version/tag nem publicar.
