# Teste da dev em outro computador

Não há nova versão/tag/release. Este roteiro testa os arquivos atuais.

## Instalar

Extraia o pacote de teste ou obtenha a dev que contém estas alterações.
Abra um terminal na pasta e execute `bash install.sh --from-checkout`.
Escolha a inicialização automática. A instalação fica em `~/BaseusPresenter`,
fora do checkout. O instalador solicita sudo apenas para dependências/USB.
Abra **Baseus Presenter** pelo menu.

Em GNOME 46 Wayland, siga o aviso de sair/entrar na sessão após preparação
ou atualização da extensão, depois abra o aplicativo novamente. Em X11,
reiniciar só o aplicativo é suficiente. GNOME diferente de 46, KDE e wlroots
não têm suporte aos efeitos Wayland nesta versão.

## Validar antes de liberar

Registre distribuição, versão GNOME, sessão X11/Wayland e monitores/escala.

- Laser, lupa, spotlight, pincel e tela preta: ligar, mover, soltar/desligar,
  conferir retorno imediato da seta. Repetir com ferramentas sobrepostas.
- No Manim fullscreen: mover o laser, usar os outros efeitos, clicar/avançar
  slides e alternar para janela. Não ativar Zoom nativo do GNOME: houve
  fragmentação de imagem no teste de coexistência.
- Com efeito ativo, sair pelo menu da bandeja. A seta deve retornar e todos
  os desenhos devem desaparecer. Reabrir, repetir e encerrar pelo SIGTERM
  do processo do Baseus (não do GNOME Shell). Em Wayland, testar também
  desabilitar a extensão com efeito ativo e habilitá-la novamente.
- Mover entre monitores, desconectar/reconectar monitor e repetir. Teste
  separadamente GNOME Wayland e X11. Cintilação residual no GNOME46 é uma
  limitação conhecida; não foi corrigida pela mudança de fullscreen.

## Reinstalar/atualizar sem publicar

Feche Baseus e execute novamente `bash install.sh --from-checkout` a partir
da nova cópia de teste. Configurações externas devem permanecer. No Wayland,
se os arquivos da extensão mudarem, o aplicativo pedirá nova sessão.
O atualizador da interface continua buscando releases publicadas: não use
esse botão para testar código ainda não publicado na dev.

Os testes automatizados executam instalador e updater em pastas temporárias,
com download, pip e sudo simulados, e verificam pacote, startup e rollback.
Isso não substitui instalar dependências reais nem testar a interface gráfica
no segundo PC. O transporte D-Bus é testado num barramento privado; o renderer
usa GJS com tracker simulado para verificar restauração e expiração.
