# Test fixtures

**Synthetic data only — never put real church material here.** Real bulletins, lyric
sheets, and decks contain member names and offering amounts and are git-ignored.

CI runs against anonymized stand-ins:
- `sample_bulletin.pdf` — a fake bulletin with the same layout, dummy names/numbers
- `sample_sheet.png` — a fake lyric sheet
- `sample_template.key` — a tiny dummy Keynote (used only by `local_only` tests on a Mac)

These let the parser, renderer, and Bible/lyrics logic be tested in CI without exposing
anyone's data.
