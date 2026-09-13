# Interface translations

The application uses Qt Linguist TS/QM catalogs with the `Baseus` context.
Portuguese is the source language; English is the fallback for unsupported system
UI languages. `ui_language` stores `auto`, `pt`, or `en`, independently of profile
and audio settings. A manual change takes effect after quitting and reopening.

## Speech and Vosk models

When adding a Vosk folder, enter its name and select its spoken language from
the list of language names and codes (for example German / Deutsch, `de`).
This is stored as `language` on the model, independently of the UI language.
Use **Model language** next to the model selector to correct this choice.
The selection describes the model you downloaded; it does not convert a model
into another language. The language list comes from Qt locales, not Argos:
a language can be used for transcription even without a translation package.

Existing models without language metadata ask on selection/startup. Cancelling
keeps the model and transcription available but translation waits for a language.
All profiles using that folder share its language. Translation reads this model
metadata rather than a stale profile `source_lang` value.

The Argos catalog is refreshed in the background when opening the application.
Destinations are filtered for the currently selected model, including after
switching profiles while the catalog is loading. Only direct package pairs are
offered for download; multi-step translations are not listed. An unavailable
saved destination is preserved but disabled, so changing unrelated settings
does not overwrite the preference. If the catalog cannot be loaded, downloads
are unavailable; already installed speech translation can still work offline.

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
