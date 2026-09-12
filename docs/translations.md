# Interface translations

The application uses Qt Linguist TS/QM catalogs with the `Baseus` context.
Portuguese is the source language; English is the fallback for unsupported system
UI languages. `ui_language` stores `auto`, `pt`, or `en`, independently of profile
and audio settings. A manual change takes effect after quitting and reopening.

Use `tr("Literal text")` from `app.i18n` for application-owned visible messages.
For dynamic messages, use positional fields: `tr("Versão {0}", version)`.
Never translate stored profile names, model paths, device names, protocol values,
transcribed speech, or configuration keys. Internal diagnostic logs and messages
from third-party tools may remain in their original language.

## Editing catalogs

1. Run `python3 tools/update_translations.py` to extract new marked messages.
2. Review `app/translations/baseus_en.ts` with Qt Linguist or a text editor.
   Preserve placeholders and remove `type="unfinished"` after translation.
3. Install the development tool `qttools5-dev-tools`, then run
   `python3 tools/update_translations.py --compile`.
   If needed, pass `--lrelease /path/to/lrelease`.
4. Run the project checks and commit both TS and QM files with the code.

End users do not need Qt Linguist or lrelease. Catalogs are inside `app/`, so
installation and updates copy them together with the program. Packages containing
the i18n module must include both languages' nonempty TS and QM files.

`app.i18n.install_translator()` loads a QTranslator before creating windows. It
also loads Qt's Portuguese built-in dialog translations when provided by PyQt5.
If an English QM file cannot be loaded, a QTranslator subclass uses the reviewed
TS catalog. This fallback requires no network access.

## Independent processes

The uninstaller runs with system Python and reads the same TS catalog through the
standard library; it does not import Qt. English messages are cached before the
installation folder is removed. The confirmation token remains `desinstalar`,
case-insensitive, in both languages, and the prompt states this explicitly.

The installer has no application files available initially. Its standalone shell
messages have Portuguese and English variants. The updater uses the same scheme;
the app passes its current UI language via `BASEUS_UI_LANGUAGE`. Shell invocations
otherwise select from `LANGUAGE` and `LC_ALL`/`LC_MESSAGES`/`LANG`.

To add another language, create and compile its catalog, extend the supported
locale mapping and selector, provide standalone shell translations, and update
package validation and tests. Review layouts in every supported language.
