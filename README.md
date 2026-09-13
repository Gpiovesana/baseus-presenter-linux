
  <a href="#-português">🇧🇷 Português</a> | <a href="#-english">🇺🇸 English</a>



---
<p align="center">
  <img width="75%" alt="resultado" src="https://github.com/user-attachments/assets/996376a3-89ca-4d0b-8522-d04eb2d23d85"/>
</p>


# 🇧🇷 Português

> A interface está disponível em português e inglês, com detecção automática do idioma do sistema e funcionamento offline.


# Baseus Presenter para Linux 🚀

Um software open-source não-oficial que desbloqueia e expande todas as funcionalidades do passador de slides Baseus Orange Dot AI no Linux. Construído com PyQt5, este projeto transforma seu passador em uma ferramenta completa para professores, palestrantes e criadores de conteúdo, trazendo ferramentas visuais, transcrição de voz offline e tradução simultânea em tempo real.

> ⚠️ **Aviso Legal:** Este é um projeto de código aberto independente. Não possui nenhuma afiliação, endosso, patrocínio ou vínculo comercial com a marca Baseus.

> 🐧 **Compatibilidade:** Testado no Zorin OS. Projetado para distribuições Linux baseadas em Debian/Ubuntu. Testes da comunidade em outras distribuições são bem-vindos.

## ✨ Funcionalidades

* **Ferramentas Visuais de Apresentação:**
  * **Laser Digital:** Um ponto virtual personalizável (cor e tamanho) na tela.
  * **Lupa (Magnifier):** Amplie áreas específicas da tela (formato circular ou retangular).
  * **Spotlight:** Escureça a tela e destaque apenas a área em volta do cursor.
  * **Caneta Digital (Pincel):** Desenhe livremente sobre qualquer aplicativo ou apresentação.
* **IA & Áudio com Processamento 100% Local (após o download inicial dos modelos):**
  * **Transcrição Push-to-Talk:** Segure ou clique no botão de microfone para transcrever sua fala para texto.
  * **Diário de Bordo:** Salva tudo o que foi falado durante a aula/palestra em um arquivo `.txt`.
  * **Tradução Simultânea:** Legendas automáticas na tela em um segundo idioma (ex: você fala em Português e a legenda aparece em Inglês).
* **Segurança e Estabilidade:**
  * O aplicativo roda em user space sem exigir privilégios de root, graças às regras udev configuradas na instalação.
  * Prevenção contra múltiplas instâncias e salvamento atômico de configurações.

## 📥 Instalação

**Opção 1: Instalação Rápida (1 linha):**

Abra o terminal e cole o comando abaixo. O instalador consulta a API do GitHub e instala a última release estável publicada (rascunhos e pré-releases são ignorados).

```bash
wget -qO- https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh | bash
```

Durante a instalação, escolha se o Baseus Presenter deve iniciar automaticamente
ao entrar no sistema: digite `y` para ativar ou `n` para desativar. Em instalações automatizadas, use `--autostart` ou `--no-autostart` para informar a escolha sem uma pergunta.

**Opção 2: Instalação Manual/Auditável (Para usuários avançados):**

Baixe o script de instalação
```bash
wget https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh

# Inspecione o código, se desejar
cat install.sh
# Execute o instalador
bash install.sh
```


## Atualização

Após confirmar, uma janela mostra a etapa de preparação da atualização e impede
novos cliques. O aplicativo fecha quando o download e a preparação terminam,
para concluir a troca e reiniciar. Falhas de preparação são exibidas na tela.

Na janela de atualização, a opção **Iniciar o Baseus Presenter automaticamente ao
entrar no sistema** reflete a configuração atual. Marque ou desmarque antes de
clicar em **Atualizar**. A escolha só é aplicada após a nova versão abrir com
sucesso; cancelar ou ocorrer uma falha preserva a configuração anterior.
Versões antigas que ainda não possuem essa opção mantêm o comportamento anterior
durante a atualização; a escolha estará disponível nas próximas atualizações.

## Desinstalação

Abra **Configurações → Geral → Desinstalar Baseus Presenter…**, ou procure
**Desinstalar Baseus Presenter** no menu de aplicativos. O terminal primeiro
mostra um aviso: é necessário digitar `DESINSTALAR` para continuar. Enter ou
fechar o terminal cancela. A senha administrativa é solicitada somente para
remover a regra USB. A confirmação aceita maiúsculas, minúsculas ou letras misturadas.

Após confirmar, uma janela independente mostra o progresso da desinstalação.
As etapas e o resultado também aparecem no terminal, inclusive se a janela não
estiver disponível. Novas instalações incluem o Zenity, usado para essa janela.

O aplicativo é encerrado antes da remoção. A pasta de instalação inteira,
o ambiente virtual, os atalhos e a inicialização automática são removidos.
Configurações, modelos e transcrições fora da pasta de instalação são preservados;
arquivos pessoais dentro dela também serão apagados. A remoção não usa a lixeira.
O recurso fica desativado em checkouts Git de desenvolvimento.

Se necessário, execute `bash ~/BaseusPresenter/uninstall.sh` (ajuste o caminho
se instalou em outra pasta). O mesmo aviso de confirmação será exibido.

## ⚙️ Como usar

Em **Configurações → Geral → Idioma da interface**, escolha **Automático — idioma
do sistema**, **Português** ou **English**. A escolha fica salva e é aplicada
depois de encerrar e abrir o aplicativo novamente. Em modo automático, português
e inglês são reconhecidos; outros idiomas usam inglês como alternativa.
Essa opção não altera os idiomas de reconhecimento de voz ou das legendas.

As traduções acompanham o aplicativo: não é necessário baixar modelos ou acessar
a internet para traduzir a interface. O instalador usa o idioma do sistema;
o desinstalador também respeita a escolha salva no aplicativo.

* Inicie o programa: Você pode iniciá-lo pelo terminal rodando `~/BaseusPresenter/.venv/bin/python3 ~/BaseusPresenter/baseus_app.py`.

* Ícone na Bandeja: Um ícone vermelho aparecerá perto do relógio do sistema. Clique com o botão direito para abrir as Configurações.

* Configurando a Voz (Vosk):

  * O reconhecimento de voz é feito localmente para garantir sua privacidade.

  * Baixe um modelo de idioma no site oficial do [Vosk Models](https://alphacephei.com/vosk/models).

  * Descompacte a pasta, vá na aba Áudio e Idioma do aplicativo, clique em + Adicionar pasta e aponte para o modelo baixado.

## 🎮 Controles do Passador
* Os botões do hardware foram mapeados via engenharia reversa para operar o sistema:

* Botão do Laser (Segurar): Ativa a ferramenta visual selecionada (Laser, Lupa ou Spotlight).

* Botão de Microfone (Clique simples): Inicia/encerra a gravação da transcrição para o arquivo de texto.

* Botão de Tradução (Clique simples): Inicia/encerra as legendas com tradução simultânea na tela.

* Botão de Risco (Segurar): Ativa o pincel para desenhar livremente na tela.

* Duplo Clique no Pincel: Limpa todos os desenhos da tela.

* Segurar botão Avançar: Alterna para a "Tela Preta" (excelente para chamar a atenção dos alunos de volta para o professor).

## 🛠️ Stack Tecnológica
* Python 3

* PyQt5 (Interface gráfica, manipulação de QThreads e QPainter overlays)

* evdev & hidraw (Leitura direta e bloqueio de inputs do hardware USB/Bluetooth)

* Vosk (Motor de Speech-to-Text Kaldi)

* Argos Translate (Tradução baseada em OpenNMT)

## 🤝 Contribuindo
Sugestões, issues e pull requests são muito bem-vindos! Sinta-se à vontade para fazer um fork do projeto e propor melhorias.



# 🇺🇸 English

> The interface is available in Portuguese and English, with automatic system language detection and offline operation.
# Baseus Presenter for Linux 🚀

An unofficial open-source software that unlocks and expands all features of the Baseus Orange Dot AI slide presenter on Linux. Built with PyQt5, this project transforms your presenter into a complete tool for teachers, speakers, and content creators, bringing visual tools, offline voice transcription, and real-time simultaneous translation.

> ⚠️ **Disclaimer:** This is an independent open-source project. It has no affiliation, endorsement, sponsorship, or commercial tie with the Baseus brand.

> 🐧 **Compatibility:** Tested on Zorin OS. Designed for Debian/Ubuntu-based Linux distributions. Community testing on other distributions is welcome.

## ✨ Features
* **Visual Presentation Tools:**

  * Digital Laser: A customizable virtual pointer (color and size) on the screen.

  * Magnifier: Zoom in on specific areas of the screen (circular or rectangular shape).

  * Spotlight: Darken the screen and highlight only the area around the cursor.

  * Digital Pen (Brush): Draw freely over any application or presentation.

* Artificial Intelligence & Audio with 100% Local Processing (after the initial model download):

  * Push-to-Talk Transcription: Click the microphone button to transcribe your speech to text.

  * Logbook: Saves everything spoken during the class/lecture in a .txt file.

  * Simultaneous Translation: Automatic on-screen subtitles in a second language (e.g., you speak in Portuguese and subtitles appear in English).

* Security and Stability:

  * The application runs in user space without requiring root privileges, thanks to the udev rules configured during installation.

  * Prevention against multiple instances and atomic saving of configurations.



## 📥 Installation

**Option 1: Quick Install (1 line)**
Open the terminal and paste the command below. The installer queries the GitHub API and installs the latest published stable release (drafts and pre-releases are ignored). 

```bash
wget -qO- https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh | bash
```

During installation, choose whether Baseus Presenter should start automatically
when you sign in: enter `y` to enable it or `n` to disable it. For automated installations, use `--autostart` or `--no-autostart` to provide the choice without a prompt.

**Option 2: Manual/Auditable Install (For advanced users)**

```bash
# Download the installation script
wget https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh

# Inspect the code, if you wish
cat install.sh

# Run the installer
bash install.sh
```

## Updates

After confirmation, a progress window shows the preparation stage and blocks
repeated clicks. The app closes after download and preparation to complete the
replacement and restart. Preparation failures are displayed on screen.

The update dialog includes **Iniciar o Baseus Presenter automaticamente ao entrar
no sistema** (Start Baseus Presenter automatically when you sign in), initially
set to the current configuration. Check or uncheck it before clicking **Atualizar**
(Update). The choice is applied only after the new version starts successfully;
cancelling or a failed update preserves the previous setting.
Older versions without this option retain their previous update behavior; the
choice becomes available for subsequent updates.

## Uninstallation

Open **Configurações → Geral → Desinstalar Baseus Presenter…** (Settings → General
→ Uninstall Baseus Presenter), or search for **Desinstalar Baseus Presenter** in
your applications menu. Interface labels follow the selected language.
The terminal first displays a warning: you must type `DESINSTALAR` to continue.
Pressing Enter or closing the terminal cancels. Your administrator password is
requested only to remove the USB permission rule. Confirmation is case-insensitive.

After confirmation, an independent window shows uninstallation progress. Steps
and the result also appear in the terminal, including when the progress window
is unavailable. New installations include Zenity, which provides this window.

The application exits before removal. The entire installation folder, virtual
environment, shortcuts, and autostart entry are removed. Settings, models, and
transcripts outside the installation folder are preserved; personal files inside
it are also deleted. Removed files are not sent to the Trash.
Uninstallation is disabled in development Git checkouts.

If needed, run `bash ~/BaseusPresenter/uninstall.sh` (adjust the path if you
installed it elsewhere). The same confirmation warning will appear.

## ⚙️ How to use

In **Settings → General → Interface language**, choose **Automatic — system
language**, **Português**, or **English**. The preference is saved and takes effect
after quitting and reopening the application. Automatic mode recognizes Portuguese
and English and falls back to English for unsupported languages. This setting does
not change speech recognition or subtitle languages.

Translations are bundled with the application; no models or internet access are
needed for the interface. The installer follows the system language, and the
uninstaller also honors the preference saved in the application.

* Start the program: You can start it via terminal by running ~/BaseusPresenter/.venv/bin/python3 ~/BaseusPresenter/baseus_app.py.

* System Tray Icon: A red icon will appear near the system clock. Right-click it to open Settings.

* Setting up Voice (Vosk):

  * Voice recognition is done locally to ensure your privacy.

  * Download a language model from the official [Vosk Models](https://alphacephei.com/vosk/models) website.

  * Extract the folder, go to the Audio and Language tab in the application, click + Add folder..., and point to the downloaded model.
  
## 🎮 Presenter Controls
* Hardware buttons were mapped via reverse engineering to operate the system:

* Laser Button (Hold): Activates the selected visual tool (Laser, Magnifier, or Spotlight).

* Microphone Button (Single click): Starts/stops the transcription recording to the text file.

* Translation Button (Single click): Starts/stops on-screen simultaneous translation subtitles.

* Draw Button (Hold): Activates the pen to draw freely on the screen.

* Double Click on Draw: Clears all drawings from the screen.

* Hold Forward Button: Toggles the "Black Screen" (great for bringing students' attention back to the lecture).

## 🛠️ Tech Stack
Python 3 | PyQt5 | evdev & hidraw | Vosk | Argos Translate

## 🤝 Contributing
Suggestions, issues, and pull requests are very welcome! Feel free to fork the project and propose improvements.
