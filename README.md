# tgdl — Telegram restricted-video downloader (macOS)

Download videos from Telegram groups/channels you belong to, **including chats
that have "restrict saving content" enabled**, straight from a Mac terminal.

The save restriction is enforced only by the official client's UI. Over the
MTProto API, an authorized *user* session still receives the media, so a normal
download works — this tool is essentially `yt-dlp` for the Telegram groups you
are already a member of.

> **Responsible use.** Only download content you are allowed to keep. Respect
> copyright and each group's rules. You are responsible for how you use this.

---

## What's in here

| File | Type | Role |
|------|------|------|
| [`tgdl`](tgdl) | bash CLI | Front-end you move to your `bin`. Locates + runs the uv scripts. |
| [`tg_setup.py`](tg_setup.py) | uv script | One-time login. Stores credentials in the macOS Keychain. |
| [`tg_download.py`](tg_download.py) | uv script | Resolves links and downloads video media with a progress bar. |
| [`downloads/`](downloads) | dir | Unified output directory (gitignored). |
| [`SECURITY.md`](SECURITY.md) | doc | Threat model and credential-handling details. |

Both Python files are **PEP 723 uv scripts**: dependencies are declared inline,
so `uv run` builds an ephemeral environment on the fly. You never create or
activate a virtualenv.

---

## Requirements

- macOS (uses the login Keychain for secret storage).
- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Telegram account that is a **member** of the group(s) you want to pull from.
- Your own `api_id` + `api_hash` from <https://my.telegram.org> → *API
  development tools*. These identify *your app*, not the group; they're free.

---

## Security model (short version)

- Secrets live in the **macOS Keychain** (service `tgdl`), never in a plaintext
  file or in git. The Keychain encrypts them at rest and gates access to your
  login.
- The stored **session string is equivalent to full access to your Telegram
  account** — treat it like a password. Anyone who steals it can act as you.
- `.gitignore` also blocks `*.session`, `.env`, and `downloads/` as a safety net.
- Revoke access any time: **Telegram app → Settings → Devices → terminate the
  session**, then `tgdl reset` locally. Full details in [SECURITY.md](SECURITY.md).

---

## Install & first-time setup

```bash
# 1. From inside this repo, make the entry points executable.
chmod +x tgdl tg_setup.py tg_download.py

# 2. Log in ONCE while the CLI is still co-located with the scripts.
#    This both authenticates AND records the repo path to
#    ~/.config/tgdl/home, so the CLI keeps working after you move it.
./tgdl setup
#   -> enter api_id, api_hash (hidden), phone
#   -> enter the login code Telegram sends you (and 2FA password if enabled)

# 3. Confirm it works.
./tgdl check          # prints "Connected as <you>"

# 4. Move the CLI onto your PATH (you do this yourself).
mv tgdl ~/bin/        # or wherever your unified bin lives
```

If you prefer not to rely on the auto-recorded path, point at the repo explicitly:

```bash
export TGDL_HOME="/Users/you/Downloads/pros/codebase/demos/tele-vid-download"
```

Add that line to `~/.zshrc` to make it permanent.

---

## Workflow

Get a message link in the Telegram desktop app: **right-click the video →
Copy Message Link**. Private-group links look like
`https://t.me/c/1234567890/42`; public ones like `https://t.me/name/42`.

```bash
# Single video
tgdl get https://t.me/c/1234567890/42

# Several at once
tgdl get https://t.me/c/1234567890/42 https://t.me/c/1234567890/57

# A whole range of message ids from one chat (inclusive)
tgdl get --chat https://t.me/c/1234567890 --range 100 180

# Send output somewhere else for one run
tgdl get https://t.me/c/1234567890/42 --out ~/Movies/tg

# Not sure of the chat id? List your dialogs:
tgdl list                 # prints "id<TAB>name" for every chat

# Grab non-video media too (photos, docs)
tgdl get https://t.me/c/1234567890/42 --all
```

Files are written to `downloads/` by default, named `<chatid>_<msgid>_<orig>` so
runs never collide. Re-running skips files already fully downloaded. Downloads
default to **videos only**; pass `--all` for any media.

Override the output directory globally with `TGDL_OUT`:

```bash
export TGDL_OUT="$HOME/Movies/telegram"
```

---

## Testing

There is no login-free unit surface (everything needs a real session), so tests
are staged from cheapest to most involved.

**1. Static checks (no account needed):**

```bash
python3 -m py_compile tg_setup.py tg_download.py   # syntax
bash -n tgdl                                        # bash parse
```

**2. Dependency resolution (downloads packages, no login):**

```bash
uv run --script tg_download.py --help              # builds env, prints usage
```

**3. Connectivity smoke test (needs `tgdl setup` first):**

```bash
tgdl check        # -> "Connected as <you> id=..."  proves session is valid
tgdl list         # -> lists your chats; proves entity access works
```

**4. End-to-end (one real, small video):**

```bash
tgdl get https://t.me/c/<id>/<msg>
ls -lh downloads/
# Verify the file plays and its size matches the message.
```

Pick a *small* clip from a save-restricted group for step 4 — that is the exact
capability being validated.

---

## Debugging

| Symptom | Cause / fix |
|---|---|
| `No stored credentials. Run: tgdl setup` | Keychain is empty. Run `tgdl setup`. |
| `Session invalid or expired. Run: tgdl setup` | Session was revoked/logged out. Re-run setup. |
| `tgdl: uv is not installed` | Install uv, or ensure it's on `PATH`. |
| `tgdl: cannot locate the scripts` | You moved `tgdl` off the repo without recording home. `export TGDL_HOME=/path/to/repo`. |
| `Unrecognized Telegram message link` | Use *Copy Message Link* (a `t.me/...` URL), not "Copy Link". |
| `Cannot find any entity corresponding to "PeerChannel..."` | Fresh session hasn't cached the chat. Run `tgdl list` once, then retry. |
| `[wait] rate limited ... sleeping Ns` | Telegram FloodWait. The tool auto-sleeps and resumes; just let it run. |
| Keychain prompt "tgdl wants to use ..." | Expected on first access after a reboot. Click *Always Allow* to stop repeats. |
| Slow downloads | `cryptg` should be installed automatically (it accelerates MTProto AES). Confirm it appears in `uv`'s resolution when running the script. |

**Verbose Telethon logging** for deeper issues:

```bash
uv run --script tg_download.py --check   # add logging by editing the script:
# import logging; logging.basicConfig(level=logging.DEBUG)
```

Inspect what's stored (values are printed by the Keychain, so do this privately):

```bash
security find-generic-password -s tgdl -a session -w   # prints the session string
```

Reset everything and start over:

```bash
tgdl reset            # clears Keychain items
# Then, in the Telegram app: Settings -> Devices -> terminate the session.
```

---

## How it works

1. `tg_setup.py` runs an interactive MTProto login and saves a Telethon
   `StringSession` (plus `api_id`/`api_hash`) into the Keychain.
2. `tg_download.py` rebuilds the client from that session, parses the `t.me`
   link into `(chat, message-id)`, fetches the message, and calls
   `download_media()`.
3. Because the request comes from an authorized user session, the server sends
   the file regardless of the chat's `noforwards` ("restrict saving") flag.

The `tgdl` wrapper only handles command dispatch and locating the scripts, so
the security-sensitive logic stays in the auditable Python files.

---

## Uninstall

```bash
tgdl reset                              # remove Keychain items
rm ~/bin/tgdl                           # remove the CLI you moved
rm -f ~/.config/tgdl/home               # remove the recorded path
# delete this repo directory when done
```
