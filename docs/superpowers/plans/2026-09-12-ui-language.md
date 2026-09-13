# Interface language implementation plan

Design approved in the task: Portuguese and English packaged offline, automatic
system UI language detection, explicit override, English fallback, restart to apply.
Speech recognition and subtitle language are independent settings.

- [x] Test locale selection, missing catalogs, Qt translation and persistence.
- [x] Add app/i18n.py with install_translator(app, preference), tr(text), and locale resolution.
- [x] Keep catalogs in app/translations so existing package copying includes them.
- [x] Add ui_language to configuration and a General tab selector storing auto/pt/en.
- [x] Mark interface messages with stable translation keys and formatting placeholders.
- [x] Provide reviewed English catalog and Portuguese source catalog, compiled as QM.
- [x] Translate standalone uninstall messages with the same TS catalog through standard Python.
- [x] Verify translated widgets, profile persistence, audio separation, package contents and full suite.
- [x] Document translation tooling, supported languages and restart behavior.

No commits or publication requested. Existing data names and protocol identifiers must not change.

Validation: the initial i18n test failed before implementation; missing-translation
package test failed before validation was added. Final pre-commit: 231 tests pass
with simulated audio. Offscreen visual inspection of Portuguese and English tabs
identified and resolved text clipping. Physical notebook validation remains manual.
