/* Search-only aliases for the command palette.

   The palette renders English (the rest of the SPA is English), but the operator types in the
   language they think in. These strings are never displayed -- CommandPalette matches a query
   against the label first and against these only to find the command -- so one file here is
   the whole exception to the "the UI speaks one language" guard in tests/test_text_integrity.py. */

export const COMMAND_KEYWORDS: Record<string, string[]> = {
  "new-project": ["новый проект", "создать проект", "каркас проекта"],
  "toggle-theme": ["тема", "переключить тему", "тёмная тема", "светлая тема"],
  "scaffold-api": ["fastapi", "создать структуру", "каркас api", "бойлерплейт"],
  "generate-tests": ["тесты", "сгенерировать тесты", "написать тесты"],
};
