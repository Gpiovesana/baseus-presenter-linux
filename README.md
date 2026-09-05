
  <a href="#-português">🇧🇷 Português</a> | <a href="#-english">🇺🇸 English</a>


---

# 🇧🇷 Português


# Baseus Presenter para Linux 🚀

Um software open-source não-oficial que desbloqueia e expande todas as funcionalidades do passador de slides Baseus Orange Dot AI no Linux. Construído com PyQt5, este projeto transforma seu passador em uma ferramenta completa para professores, palestrantes e criadores de conteúdo, trazendo ferramentas visuais, transcrição de voz offline e tradução simultânea em tempo real.

> ⚠️ **Aviso Legal:** Este é um projeto de código aberto independente. Não possui nenhuma afiliação, endosso, patrocínio ou vínculo comercial com a marca Baseus.

## ✨ Funcionalidades

* **Ferramentas Visuais de Apresentação:**
  * **Laser Digital:** Um ponto virtual personalizável (cor e tamanho) na tela.
  * **Lupa (Magnifier):** Amplie áreas específicas da tela (formato circular ou retangular).
  * **Spotlight:** Escureça a tela e destaque apenas a área em volta do cursor.
  * **Caneta Digital (Pincel):** Desenhe livremente sobre qualquer aplicativo ou apresentação.
* **Inteligência Artificial & Áudio (100% Offline):**
  * **Transcrição Push-to-Talk:** Segure ou clique no botão de microfone para transcrever sua fala para texto.
  * **Diário de Bordo:** Salva tudo o que foi falado durante a aula/palestra em um arquivo `.txt`.
  * **Tradução Simultânea:** Legendas automáticas na tela em um segundo idioma (ex: você fala em Português e a legenda aparece em Inglês).
* **Segurança e Estabilidade:**
  * Regras automáticas de `udev` rodando em *user space* (não requer root após a instalação).
  * Prevenção contra múltiplas instâncias e salvamento atômico de configurações.

## 📥 Instalação Rápida (Recomendado)

Abra o seu terminal no Linux (testado em Ubuntu, Zorin OS e Linux Mint) e cole o comando abaixo. Ele fará o download das dependências, criará as regras de segurança no Kernel e instalará o aplicativo na sua pasta Home.

```bash
wget -qO- [https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh](https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh) | bash 
```


(Certifique-se de reiniciar o computador após a instalação para que o sistema aplique as novas permissões do grupo de segurança).

## ⚙️ Como usar
* Inicie o programa: Você pode iniciá-lo pelo terminal rodando python3 ~/BaseusPresenter/baseus_app.py (ou adicioná-lo aos aplicativos de inicialização do seu sistema).

* Ícone na Bandeja: Um ícone vermelho aparecerá perto do relógio do sistema. Clique com o botão direito para abrir as Configurações.

* Configurando a Voz (Vosk):

  * O reconhecimento de voz é feito localmente para garantir sua privacidade.

  * Baixe um modelo de idioma no site oficial do [Vosk Models](https://alphacephei.com/vosk/models).

  * Descompacte a pasta, vá na aba Áudio e Idioma do aplicativo, clique em + Adicionar pasta e aponte para o modelo baixado.

## 🎮 Controles do Passador
* Os botões do hardware foram mapeados via engenharia reversa para operar o sistema:

* Botão do Laser (Segurar): Ativa a ferramenta visual selecionada (Laser, Lupa ou Spotlight).

* Botão de Microfone (Clique simples): Inicia/Pausa a gravação da transcrição para o arquivo de texto.

* Botão de Tradução (Clique simples): Inicia/Pausa as legendas com tradução simultânea na tela.

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
# Baseus Presenter for Linux 🚀
An unofficial open-source software that unlocks and expands all features of the Baseus Orange Dot AI slide presenter on Linux. Built with PyQt5, this project transforms your presenter into a complete tool for teachers, speakers, and content creators, bringing visual tools, offline voice transcription, and real-time simultaneous translation.

> ⚠️ **Disclaimer:** This is an independent open-source project. It has no affiliation, endorsement, sponsorship, or commercial tie with the Baseus brand.

## ✨ Features
* **Visual Presentation Tools:**

  * Digital Laser: A customizable virtual pointer (color and size) on the screen.

  * Magnifier: Zoom in on specific areas of the screen (circular or rectangular shape).

  * Spotlight: Darken the screen and highlight only the area around the cursor.

  * Digital Pen (Brush): Draw freely over any application or presentation.

  * Artificial Intelligence & Audio (100% Offline):

  * Push-to-Talk Transcription: Click the microphone button to transcribe your speech to text.

  * Logbook: Saves everything spoken during the class/lecture in a .txt file.

  * Simultaneous Translation: Automatic on-screen subtitles in a second language (e.g., you speak in Portuguese and subtitles appear in English).

  * Security and Stability:

  * Automatic udev rules running in user space (does not require root after installation).

  * Prevention against multiple instances and atomic saving of configurations.

## 📥 Quick Install (Recommended)
Open your Linux terminal (tested on Ubuntu, Zorin OS, and Linux Mint) and paste the command below. It will download dependencies, create security rules in the Kernel, and install the application in your Home folder.

```Bash
wget -qO- [https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh](https://raw.githubusercontent.com/Gpiovesana/baseus-presenter-linux/main/install.sh) | bash
```
(Make sure to restart your computer after installation so the system applies the new security group permissions).

## ⚙️ How to Use
* Start the program: You can start it via terminal by running python3 ~/BaseusPresenter/baseus_app.py (or add it to your system's startup applications).

* System Tray Icon: A red icon will appear near the system clock. Right-click it to open Settings.

* Setting up Voice (Vosk):

  * Voice recognition is done locally to ensure your privacy.

  * Download a language model from the official [Vosk Models](https://alphacephei.com/vosk/models) website.

  * Extract the folder, go to the Audio and Language tab in the application, click + Add folder..., and point to the downloaded model.

## 🎮 Presenter Controls
* Hardware buttons were mapped via reverse engineering to operate the system:

* Laser Button (Hold): Activates the selected visual tool (Laser, Magnifier, or Spotlight).

* Microphone Button (Single click): Starts/Pauses the transcription recording to the text file.

* Translation Button (Single click): Starts/Pauses on-screen simultaneous translation subtitles.

* Draw Button (Hold): Activates the pen to draw freely on the screen.

* Double Click on Draw: Clears all drawings from the screen.

* Hold Forward Button: Toggles the "Black Screen" (great for bringing students' attention back to the lecture).

## 🛠️ Tech Stack
Python 3 | PyQt5 | evdev & hidraw | Vosk | Argos Translate

## 🤝 Contributing
Suggestions, issues, and pull requests are very welcome! Feel free to fork the project and propose improvements.
