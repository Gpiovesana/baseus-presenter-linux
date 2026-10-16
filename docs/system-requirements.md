# Requisitos de sistema e transição de instalações

`app/system-requirements.json` declara schema 1 e revisão 1. Revisões são
contratos exatos: uma revisão maior não implica compatibilidade com uma menor.
A revisão 1 corresponde ao procedimento atual de `install.sh`: apt instala
curl, python3, python3-venv, python3-pip, python3-dev, build-essential,
libportaudio2, portaudio19-dev, libxcb-cursor0, libxcb-xinerama0, xterm e zenity;
udev concede uaccess para abc8:ca08 (hidraw/input) e uinput.

Alterar requisitos exige revisar o manifesto e o procedimento do instalador,
incluindo `APPLIED_SYSTEM_REVISION`. Não alterar os requisitos na release
preparatória que introduz esta proteção.

O instalador grava `.system-requirements.json` na instalação somente depois
de todas as suas etapas terem sucesso. A gravação é atômica e uma falha causa
rollback. O recibo registra o procedimento aplicado, não confirma permissões
atuais, conexão do passador ou saúde dos pacotes. A atualização interna apenas
valida e preserva esse recibo. Manifesto/recibo ausente, corrompido, desconhecido
ou diferente bloqueia antes de READY, venv e troca da instalação ativa. Na
recuperação de transação interrompida, vale o recibo do backup a restaurar.

## Instalações antigas

Não há adoção automática nem opção de ignorar o preflight. Feche o aplicativo
e execute novamente o instalador atual, escolhendo `--autostart` ou
`--no-autostart`. Configurações e modelos ficam fora da instalação e são
preservados. A reinstalação reaplica apt/udev e só então pode emitir o recibo.

Um updater antigo já instalado não executa o preflight novo. Ele pode baixar
a versão preparatória, mas não fabrica um recibo: a próxima atualização pelo
fluxo novo exigirá reinstalação. A publicação preparatória deve conservar
requisitos da revisão 1. Não se deve publicar mudança de requisitos assumindo
que todos os usuários instalaram a preparação; clientes que a pularam ainda
executam o updater antigo. A distribuição de uma revisão incompatível exige
um plano separado para esses clientes (canal novo ou reinstalação explícita).

Testes de shell usam downloads, sudo e Python em venv simulados, executando a
transação real em diretórios temporários; não instalam pacotes no computador.
