# Contributing to tgdl

Thanks for helping out. This is a deliberately **small, auditable** tool, so the
bar for changes is "does it make the core job better without growing the surface
area?" A few things to know before you open a PR.

## Scope — what fits, what doesn't

`tgdl` does one thing: download videos (incl. from save-restricted groups you
belong to) from a link or an id range, safely and with zero setup.

**In scope:** correctness fixes, new/odd `t.me` link formats, reliability,
security, small CLI ergonomics, docs, tests.

**Out of scope (on purpose):** bot mode, a GUI/web UI, upload/forward/export,
config-file frameworks, multi-account managers. If you want the maximalist
toolkit, [`iyear/tdl`](https://github.com/iyear/tdl) already does it well —
competing with it would cost the "two short files you can read and trust" value
this project exists for. Please open an issue to discuss before large changes.

## Dev setup

You only need [uv](https://docs.astral.sh/uv/). No virtualenv, no `pip install`.

```bash
git clone https://github.com/serratusCZ/tgdl.git
cd tgdl
```

## Before you push — run what CI runs

```bash
python3 -m py_compile tg_download.py tg_setup.py          # syntax
bash -n tgdl                                              # bash parse
uvx ruff check tg_download.py tg_setup.py                # lint (keep it clean)
uv run --with pytest --with telethon --with keyring --with tqdm pytest -q tests/
```

All four must pass. CI repeats them on Python 3.10 and 3.12.

Anything account-bound (real downloads, `setup`, `logout`) can't run in CI —
verify those by hand and describe what you did in the PR.

## Tests

Pure helpers (`parse_link`, `sanitize`, `build_name`, `is_video`, `_human`) are
unit-tested in [`tests/test_units.py`](tests/test_units.py) — no login needed.
**If you touch link parsing or naming, add a case there.** New `t.me` shapes
especially: add the pattern (with ids redacted) as a `parse_link` parametrize
entry.

## Style

- Match the surrounding code: small functions, type hints, sparse comments that
  explain *why* not *what*.
- Keep `ruff` clean.
- Don't add dependencies without a strong reason; each one is in the PEP 723
  header of both scripts and must be justified.

## Security rules (non-negotiable)

- **Never commit secrets.** No `api_hash`, no session strings, no real chat ids.
  Credentials live in the macOS Keychain, never on disk — keep it that way.
- Don't pass secrets as command-line arguments (visible in `ps`); prompt or read
  from the Keychain.
- If you paste logs in an issue/PR, scrub ids and run with only the verbosity you
  need. See [SECURITY.md](SECURITY.md).

## Reporting an unrecognized link

Found a `t.me/...` link `tgdl` mishandles? Open an
[Unsupported link format](../../issues/new?template=unsupported_link.yml) issue.
Tell us the *pattern* (redact the numbers) and where the media lives (post,
comment, forum topic…). That's exactly how comment-link support got added.

## Commits & PRs

- Small, focused commits with a clear subject line.
- Fill in the PR checklist.
- Link the issue you're addressing.

## Responsible use

This tool is for archiving content **you have the right to keep**. Please respect
copyright and each group's rules, and don't use it to redistribute others' work.
