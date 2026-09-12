"""Offline UI translations. Qt for the app, the same TS catalog for system Python."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

TRANSLATIONS = Path(__file__).parent / "translations"
_language = "pt"
_translator = None
_qt_translator = None
_english = None


def resolve_language(preference="auto", languages=None):
    if preference in ("pt", "en"):
        return preference
    if languages is None:
        languages = []
        for key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(key)
            if value:
                languages.extend(value.split(":"))
                if key != "LANGUAGE":
                    break
    for language in languages:
        code = language.replace("-", "_").split("_")[0].split(".")[0].lower()
        if code in ("pt", "en"):
            return code
    return "en"


def english_catalog():
    global _english
    if _english is None:
        try:
            tree = ET.parse(TRANSLATIONS / "baseus_en.ts")
            _english = {message.findtext("source"): message.findtext("translation")
                        for message in tree.findall(".//message")
                        if message.findtext("translation")}
        except (OSError, ET.ParseError):
            _english = {}
    return _english


def tr(source, *args):
    if _translator is not None:
        from PyQt5.QtCore import QCoreApplication
        text = QCoreApplication.translate("Baseus", source)
    else:
        text = english_catalog().get(source, source) if _language == "en" else source
    return text.format(*args) if args else text


def install_translator(app, preference="auto"):
    from PyQt5.QtCore import QLocale, QTranslator, QLibraryInfo
    global _language, _translator, _qt_translator
    if _translator is not None:
        app.removeTranslator(_translator)
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
    _language = resolve_language(preference, QLocale.system().uiLanguages())
    _translator = None
    _qt_translator = None
    if _language == "pt":
        native = QTranslator(app)
        if native.load("qtbase_pt_BR", QLibraryInfo.location(QLibraryInfo.TranslationsPath)):
            app.installTranslator(native)
            _qt_translator = native
    if _language == "en":
        translator = QTranslator(app)
        if not translator.load(str(TRANSLATIONS / "baseus_en.qm")):
            class CatalogTranslator(QTranslator):
                def isEmpty(self):
                    return False

                def translate(self, context, source, disambiguation=None, n=-1):
                    return english_catalog().get(source, "") if context == "Baseus" else ""
            translator = CatalogTranslator(app)
        app.installTranslator(translator)
        _translator = translator
    return _language


def current_language():
    return _language


def configure_standalone():
    """Honor the saved UI preference without importing Qt or depending on the venv."""
    global _language
    preference = "auto"
    try:
        with (Path.home() / ".config/baseus_presenter/baseus_pointer.json").open(encoding="utf-8") as stream:
            preference = json.load(stream).get("ui_language", "auto")
    except (OSError, ValueError, AttributeError):
        pass
    _language = resolve_language(preference)
    if _language == "en":
        english_catalog()  # Load before the installation directory is removed.
    return _language
