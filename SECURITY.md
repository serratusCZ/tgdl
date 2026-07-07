# Security model

This tool authenticates as **your Telegram user account** (not a bot), because
only a user session can read group media and is unaffected by the "restrict
saving content" flag. That makes the credentials highly sensitive. This document
explains what is stored, where, and how to contain the risk.

## Assets and sensitivity

| Asset | Sensitivity | Why |
|---|---|---|
| `session` string | **Critical** | Full, ongoing access to your Telegram account. A thief can read chats and send messages as you, without your phone or 2FA. |
| `api_hash` | Moderate | Identifies your `my.telegram.org` app. Should stay private. |
| `api_id` | Low | Numeric app id; not really secret but stored alongside the rest. |

## Where secrets live

All three are stored in the **macOS login Keychain** under service name `tgdl`
(accounts `api_id`, `api_hash`, `session`), via the `keyring` library.

- Encrypted at rest by macOS; unlocked with your login password.
- Access is mediated by the OS. The first time `uv`'s ephemeral Python reads an
  item you may see a Keychain authorization prompt — choose *Always Allow* to
  bind access to these scripts.
- **Nothing secret is written to the repo or any dotfile.** No `.session` file,
  no `.env`. The session never touches disk in plaintext.

Defense in depth: `.gitignore` still blocks `*.session`, `.env*`, and
`downloads/`, so an accidental future change can't leak secrets through git.

## Design choices that raise the bar

- **Keychain over plaintext.** The common pattern (a `.session` file or a
  `.env`) leaves account-equivalent secrets readable by any process running as
  you and easy to commit by mistake. The Keychain gates and encrypts them.
- **Hidden entry.** `api_hash` and the 2FA password are read with `getpass`, so
  they don't echo to the terminal or land in shell history.
- **No secrets in argv.** Credentials are never passed as command-line
  arguments (which are visible in `ps`); they're prompted for or read from the
  Keychain.
- **Minimal surface.** The bash wrapper contains no secrets logic; all handling
  is in two short, auditable Python files.

## Your responsibilities

- Keep FileVault (full-disk encryption) on. Keychain security assumes it.
- Use a strong login password and lock your screen; Keychain unlocks with login.
- Don't paste the session string anywhere or copy it to another machine.
- Prefer downloading *small, specific* clips; bulk scraping invites FloodWait
  limits and may violate a group's rules.

## Revocation / incident response

If you suspect the session leaked, or you're done using the tool:

1. **`tgdl logout`** — revokes the session on Telegram's servers (`auth.logOut`)
   and then clears the Keychain. This immediately invalidates the string
   everywhere — the most important step, and now a single command.
   - If your Mac can't reach Telegram, do it from another device instead:
     **Telegram app → Settings → Devices (Active Sessions)** → terminate the
     session, then `tgdl reset` to clear the local Keychain items.
2. If `api_hash` may be compromised, reset it at <https://my.telegram.org>.

## Out of scope

- This tool does not defeat end-to-end-encrypted *secret chats* (media there
  isn't in cloud groups anyway).
- It provides no protection if your Mac user account itself is compromised —
  malware running as you can already reach your Keychain and Telegram sessions.
