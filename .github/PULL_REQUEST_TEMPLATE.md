## What & why

<!-- One or two sentences. Link the issue if there is one (e.g. Closes #12). -->

## How I verified

<!-- CI covers the login-free part. Describe any by-hand check of account-bound
     behavior (real download, setup, logout) — with ids/secrets redacted. -->

## Checklist

- [ ] `python3 -m py_compile tg_download.py tg_setup.py` and `bash -n tgdl` pass
- [ ] `uvx ruff check tg_download.py tg_setup.py` is clean
- [ ] `uv run --with pytest --with telethon --with keyring --with tqdm pytest -q tests/` passes
- [ ] Added/updated a test if I touched link parsing or naming
- [ ] No secrets or real chat ids in the diff
- [ ] Stays in scope — small & auditable (see [CONTRIBUTING](../CONTRIBUTING.md))
