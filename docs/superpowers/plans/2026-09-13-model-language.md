# Idioma por modelo Vosk

Desenho aprovado na conversa: manter nome e pasta, acrescentar seleção de
idioma com nome legível e código. Salvar `language` no catálogo de modelos.
Modelos antigos pedem definição ao selecionar; cancelar preserva transcrição,
mas não permite assumir uma origem para tradução. Interface é independente.

## Implementação

1. Criar testes de cadastro, cancelamento, modelos antigos, troca de modelo e
   perfil, origem usada no áudio e catálogo atualizado do Argos. Observar falhas.
2. Derivar origem do modelo em `app/config.py`; atualizar cadastro e seleção em
   `app/gui.py`, com nomes de idiomas via QLocale. Reutilizar um catálogo de pares
   atualizado em background, filtrando pelo modelo atual ao receber resultados.
3. Proteger tradução sem origem em `app/audio.py`; preservar destino salvo sem
   oferecer download de pares ausentes. Atualizar traduções TS/QM e documentação.
4. Rodar testes focados, suíte completa com áudio simulado e inspeção visual.
   Não fazer commit, push, merge ou release; o usuário fará a publicação.

## Resultado

Implementado e verificado: quatro testes iniciais falharam antes da implementação;
o teste adicional de diálogo reentrante também reproduziu a falha antes da correção.
Suíte final: 239 testes passaram com ALSA simulado, incluindo testes de catálogo
Argos com rede simulada. Fiação Qt e `git diff --check` passaram. Janela e diálogo
em inglês inspecionados com Qt offscreen. Traduções TS/QM recompiladas com lrelease.
Ainda não validado com fala real, hardware ou download real do Argos.
