import unittest
import ast
import string
from pathlib import Path
from PyQt5.QtCore import QCoreApplication
from app import i18n


class TestLanguage(unittest.TestCase):
    def test_catalog_covers_marked_messages_and_preserves_placeholders(self):
        catalog = i18n.english_catalog()
        for path in Path(i18n.__file__).parent.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    self.assertIn(node.args[0].value, catalog, f"{path}:{node.lineno}")
        formatter = string.Formatter()
        for source, translated in catalog.items():
            self.assertEqual(
                sorted(field for _, field, _, _ in formatter.parse(source) if field is not None),
                sorted(field for _, field, _, _ in formatter.parse(translated) if field is not None),
                source,
            )

    def test_compiled_catalog_matches_reviewed_text(self):
        from PyQt5.QtCore import QTranslator
        translator = QTranslator()
        self.assertTrue(translator.load(str(i18n.TRANSLATIONS / "baseus_en.qm")))
        for source, translated in i18n.english_catalog().items():
            self.assertEqual(translator.translate("Baseus", source.encode("utf-8")), translated)

    def test_locale_and_override_selection(self):
        for preference, languages, expected in (
            ("auto", ["pt-BR"], "pt"), ("auto", ["pt_PT"], "pt"),
            ("auto", ["en-US"], "en"), ("auto", ["de-DE"], "en"),
            ("auto", ["de-DE", "pt-BR"], "pt"), ("en", ["pt-BR"], "en"),
            ("pt", ["en-US"], "pt"), ("invalid", [], "en"),
        ):
            with self.subTest(preference=preference, languages=languages):
                self.assertEqual(i18n.resolve_language(preference, languages), expected)

    def test_english_catalog_and_portuguese_source(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        try:
            i18n.install_translator(app, "en")
            self.assertEqual(i18n.tr("Verificar Atualizações"), "Check for Updates")
            self.assertEqual(QCoreApplication.translate("Baseus", "Cancelar"), "Cancel")
            i18n.install_translator(app, "pt")
            self.assertEqual(i18n.tr("Verificar Atualizações"), "Verificar Atualizações")
        finally:
            i18n.install_translator(app, "pt")
