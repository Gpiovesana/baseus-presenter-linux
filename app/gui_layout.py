"""Composição visual da MainWindow, usando seus controles e callbacks reais."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
                             QStackedWidget,QScrollArea,QSizePolicy)
from .i18n import tr
from .gui_style import STYLE
from .gui_visuals import Device,EffectCanvas,control_descriptions


def text(value,name=None):
    widget=QLabel(value)
    widget.setWordWrap(True)
    if name: widget.setObjectName(name)
    return widget


def card(title,note):
    frame=QFrame(objectName='card')
    frame.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
    layout=QVBoxLayout(frame)
    layout.setContentsMargins(18,16,18,16)
    layout.setSpacing(12)
    layout.addWidget(text(title,'title'))
    layout.addWidget(text(note,'muted'))
    return frame,layout


def button(title,callback):
    result=QPushButton(title)
    result.clicked.connect(callback)
    return result


def scroll_page(content):
    scroll=QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    return scroll


def page(title,note,side_title,side_note):
    root=QWidget()
    layout=QHBoxLayout(root)
    layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    content=QWidget()
    main=QVBoxLayout(content)
    main.setContentsMargins(24,24,24,16);main.setSpacing(14)
    main.addWidget(text(title,'heading'));main.addWidget(text(note,'muted'))
    layout.addWidget(scroll_page(content),1)
    side=QFrame(objectName='details');side.setFixedWidth(306)
    details=QVBoxLayout(side);details.setContentsMargins(24,28,24,24);details.setSpacing(18)
    details.addWidget(text(side_title,'heading'));details.addWidget(text(side_note))
    layout.addWidget(side)
    return root,main,details


def build_layout(w):
    w.setWindowTitle(tr('Baseus Presenter — Configurações'))
    w.resize(1280,820);w.setMinimumSize(1120,760)
    w.setStyleSheet(STYLE+'''
QFrame#card { background: #20262f; border: 1px solid #35404e; border-radius: 10px; }
QCheckBox { background: transparent; padding: 4px 0; }
QComboBox { min-height: 18px; }
QScrollBar:vertical { background: #181b20; width: 10px; margin: 3px; }
QScrollBar::handle:vertical { background: #4b5c72; min-height: 30px; border-radius: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
''')
    central=QWidget();w.setCentralWidget(central)
    layout=QVBoxLayout(central);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    header=QFrame(objectName='header');row=QHBoxLayout(header);row.setContentsMargins(26,20,26,20)
    logo=QLabel();logo.setPixmap(w.windowIcon().pixmap(38,38));row.addWidget(logo)
    titles=QVBoxLayout();titles.addWidget(text('Baseus Presenter','title'))
    titles.addWidget(text(tr('Orange Dot AI · Seu controle de apresentação'),'muted'));row.addLayout(titles,1)
    w.lbl_battery.setStyleSheet('color: #a6dcbb; background: #23332d; border: 1px solid #3b5b4a; border-radius: 14px; padding: 7px 12px;')
    row.addWidget(w.lbl_battery);layout.addWidget(header)
    profile_bar=QFrame(objectName='profiles');row=QHBoxLayout(profile_bar);row.setContentsMargins(24,12,24,12)
    row.addWidget(text(tr('Perfil:')));w.combo_profiles.setMinimumWidth(210);row.addWidget(w.combo_profiles)
    row.addWidget(button(tr('Novo Perfil'),w.new_profile))
    w.btn_delete_profile=button(tr('Excluir'),w.delete_profile);row.addWidget(w.btn_delete_profile)
    row.addStretch();row.addWidget(text(tr('Perfis manuais'),'muted'));layout.addWidget(profile_bar)
    body=QHBoxLayout();body.setSpacing(0)
    sidebar=QFrame(objectName='sidebar');sidebar.setFixedWidth(192)
    nav=QVBoxLayout(sidebar);nav.setContentsMargins(16,28,16,20);nav.setSpacing(12)
    nav.addWidget(text(tr('DISPOSITIVO'),'section'))
    w.pages=QStackedWidget();w.nav_buttons=[]
    def show_page(index):
        w.pages.setCurrentIndex(index)
        for i,item in enumerate(w.nav_buttons):item.setChecked(i==index)
    for index,name in enumerate((tr('Botões'),tr('Ponteiro e efeitos'),tr('Áudio e tradução'),tr('Configurações'))):
        item=button(name,lambda checked,index=index:show_page(index));item.setCheckable(True)
        nav.addWidget(item);w.nav_buttons.append(item)
    nav.addStretch();nav.addWidget(text(tr('Uma interface mais clara para apresentar.'),'muted'))
    body.addWidget(sidebar);body.addWidget(w.pages,1);layout.addLayout(body,1)

    root,main,details=page(tr('Conheça seu passador'),tr('Selecione um botão para ver como ele funciona.'),tr('Laser digital'),tr('Segure para apontar'))
    device=Device();main.addWidget(device,1)
    main.addWidget(text(tr('Ilustração esquemática · Funções atuais, sem remapeamento de botões.'),'muted'))
    action1=text('', 'section');desc1=text('');action2=text('', 'section');desc2=text('')
    for item in (action1,desc1,action2,desc2):details.addWidget(item)
    details.addWidget(button(tr('Ajustar ponteiro e efeitos'),lambda:show_page(1)));details.addStretch()
    title_label=details.itemAt(0).widget();subtitle_label=details.itemAt(1).widget()
    def select(key):
        info=control_descriptions()[key]
        for item,value in zip((title_label,subtitle_label,action1,desc1,action2,desc2),info):item.setText(value)
        device.select(key)
    device.selected.connect(select);select('laser');w.pages.addWidget(root)

    root,main,details=page(tr('Ponteiro e efeitos'),tr('Escolha uma ferramenta e veja os ajustes no slide de exemplo.'),tr('Laser digital'),tr('Ajustes do perfil selecionado.'))
    modes=QHBoxLayout();main.addLayout(modes)
    w.effects_canvas=EffectCanvas();main.addWidget(w.effects_canvas,1)
    main.addWidget(text(tr('Mova o mouse sobre o slide para experimentar. Nenhuma captura de tela é feita.'),'muted'))
    fields={};w.effect_value_labels={}
    for key,name,slider in [('laser_size',tr('Tamanho do Laser:'),w.laser_slider),('lupa_size',tr('Tamanho da Lupa:'),w.lupa_slider),('spotlight_size',tr('Área iluminada'),w.spotlight_slider),('spotlight_opacity',tr('Escurecimento'),w.spotlight_opacity)]:
        field=QWidget();box=QVBoxLayout(field);box.setContentsMargins(0,8,0,0)
        value=text('');box.addWidget(value);box.addWidget(slider)
        slider.setAccessibleName(name)
        def update_label(number,value=value,name=name,key=key):
            suffix=f'{round(number/255*100)}%' if key=='spotlight_opacity' else f'{number} px'
            value.setText(name+'   '+suffix)
        slider.valueChanged.connect(update_label)
        update_label(slider.value())
        fields[key]=field;w.effect_value_labels[key]=(value,name);details.addWidget(field)
    for key,item in [('laser_color',w.btn_laser_color),('pincel_color',w.btn_pincel_color)]:fields[key]=item;details.addWidget(item)
    field=QWidget();box=QVBoxLayout(field);box.setContentsMargins(0,8,0,0)
    box.addWidget(text(tr('Formato da Lupa:')))
    box.addWidget(w.combo_lupa_shape)
    fields['lupa_shape']=field;details.addWidget(field)
    details.addStretch();w.effect_buttons={}
    effect_titles={'laser':tr('Laser digital'),'lupa':tr('Lupa'),'spotlight':tr('Spotlight'),'pincel':tr('Pincel')}
    effect_heading=details.itemAt(0).widget()
    def choose_effect(mode):
        for key,item in w.effect_buttons.items():item.setChecked(key==mode)
        effect_heading.setText(effect_titles[mode])
        visible={'laser':('laser_size','laser_color'),'lupa':('lupa_size','lupa_shape'),'spotlight':('spotlight_size','spotlight_opacity'),'pincel':('pincel_color',)}[mode]
        for key,item in fields.items():item.setVisible(key in visible)
        w.effects_canvas.mode=mode;w.effects_canvas.update()
    for key,name in effect_titles.items():
        item=button(name,lambda checked,key=key:choose_effect(key));item.setCheckable(True)
        w.effect_buttons[key]=item;modes.addWidget(item)
    choose_effect('laser');w.pages.addWidget(root)

    root,main,details=page(tr('Áudio e tradução'),tr('Prepare a transcrição e as legendas do seu próximo encontro.'),tr('Sua voz, em texto'),tr('Use os botões de microfone e tradução do passador para iniciar ou encerrar cada função.'))
    frame,box=card(tr('Entrada e reconhecimento'),tr('Estas escolhas acompanham o perfil selecionado.'))
    box.addWidget(text(tr('Microfone:')));box.addWidget(w.combo_mic)
    box.addWidget(text(tr('Modelo de Voz:')));box.addWidget(w.combo_models)
    w.lbl_model_language=text('','muted');box.addWidget(w.lbl_model_language)
    w.combo_models.currentIndexChanged.connect(w.refresh_model_language)
    actions=QHBoxLayout()
    w.btn_add_model=button(tr('Adicionar'),w.add_model);w.btn_remove_model=button(tr('Remover'),w.delete_model)
    w.btn_model_language=button(tr('Idioma do modelo'),lambda:w._ensure_model_language(force=True))
    for item in (w.btn_add_model,w.btn_remove_model,w.btn_model_language):actions.addWidget(item)
    box.addLayout(actions);main.addWidget(frame)
    frame,box=card(tr('Legendas traduzidas'),tr('O idioma de origem vem do modelo de voz. Escolha aqui o destino.'))
    box.addWidget(text(tr('Traduzir para:')));box.addWidget(w.combo_lang);main.addWidget(frame)
    frame,box=card(tr('Arquivos de transcrição'),tr('Pasta compartilhada por todos os perfis · arquivos .txt'))
    box.addWidget(w.lbl_txt_path);w.btn_txt_dir=button(tr('Alterar Destino'),w.pick_txt_dir);box.addWidget(w.btn_txt_dir);main.addWidget(frame)
    main.addStretch();details.addWidget(text(tr('Reconhecimento e tradução locais após a preparação dos modelos.'),'muted'));details.addStretch();w.pages.addWidget(root)

    root,main,details=page(tr('Configurações'),tr('Preferências do aplicativo e manutenção em um só lugar.'),tr('Tudo no seu lugar'),tr('Idioma da interface e ação ao fechar a janela são escolhas globais. Efeitos, áudio, tradução e exibição de legendas acompanham cada perfil.'))
    frame,box=card(tr('Aplicativo'),tr('Estas preferências valem para todos os perfis.'))
    box.addWidget(text(tr('Idioma da interface:')));box.addWidget(w.combo_ui_language)
    box.addWidget(text(tr('A mudança de idioma será aplicada ao reiniciar o aplicativo.'),'muted'))
    box.addWidget(text(tr('Ao clicar no X da janela:')));box.addWidget(w.combo_close);main.addWidget(frame)
    frame,box=card(tr('Legendas durante a gravação'),tr('Esta escolha acompanha o perfil selecionado no topo.'))
    box.addWidget(w.check_legenda);main.addWidget(frame)
    frame,box=card(tr('Versão e atualizações'),tr('Confira novas versões e a opção de inicialização automática.'))
    from .updater import read_local_version
    box.addWidget(text(tr('Versão do código: {0}',read_local_version())));box.addWidget(w.btn_check_update)
    box.addWidget(text(tr('A inicialização automática é escolhida na instalação ou na confirmação de uma atualização.'),'muted'));main.addWidget(frame)
    frame,box=card(tr('Desinstalação'),tr('Disponível no aplicativo instalado. Requer confirmação explícita.'))
    w.btn_uninstall.setStyleSheet('color: #f4b9b9; border-color: #865252;')
    box.addWidget(w.btn_uninstall);main.addWidget(frame);main.addStretch();details.addStretch();w.pages.addWidget(root)
    for widget in (w.combo_mic,w.combo_models,w.combo_lang,w.combo_ui_language,w.combo_close,w.combo_lupa_shape):widget.setMinimumHeight(38)
    show_page(0)
