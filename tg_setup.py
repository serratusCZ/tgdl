#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "telethon>=1.36",
#     "cryptg>=0.4",
#     "keyring>=24",
# ]
# ///
"""One-time interactive login for tgdl.

Authenticates a Telegram *user* account via MTProto and stores the api_id,
api_hash and the resulting session string in the macOS Keychain (service
name "tgdl"). Nothing secret is written to disk in plaintext.

Run indirectly through the CLI:   tgdl setup
Reset stored credentials:         tgdl reset
"""
from __future__ import annotations

import asyncio
import getpass
import sys

import keyring
from telethon import TelegramClient
from telethon.sessions import StringSession

SERVICE = "tgdl"
KEYS = ("api_id", "api_hash", "session")


def _delete(key: str) -> bool:
    try:
        keyring.delete_password(SERVICE, key)
        return True
    except keyring.errors.PasswordDeleteError:
        return False


def reset() -> None:
    removed = sum(_delete(key) for key in KEYS)
    print(f"Removed {removed} stored credential item(s) from the Keychain.")


async def logout() -> None:
    """Revoke the session on Telegram's servers and drop the local session.

    Only the session is cleared; api_id/api_hash are kept so logging back in
    needs just phone + code (run `tgdl reset` to wipe those too). Unlike `reset`
    (local-only), this invalidates the session everywhere, so a leaked session
    string becomes useless. Falls back to a local clear if the session is
    already gone or the server is unreachable.
    """
    api_id = keyring.get_password(SERVICE, "api_id")
    api_hash = keyring.get_password(SERVICE, "api_hash")
    session = keyring.get_password(SERVICE, "session")

    if session and api_id and api_hash:
        client = TelegramClient(StringSession(session), int(api_id), api_hash)
        await client.connect()
        try:
            if await client.is_user_authorized():
                ok = await client.log_out()  # server-side auth.logOut
                print("Server-side session revoked."
                      if ok else "Server did not confirm logout; revoke it in the Telegram app.")
            else:
                print("Session already invalid server-side.")
        finally:
            await client.disconnect()
    else:
        print("No stored session found.")

    _delete("session")
    if api_id and api_hash:
        print("Cleared the local session; kept api_id/api_hash for a quick re-login.")
        print("Log back in with:  tgdl setup   (reuses stored api creds — just phone + code)")
    else:
        print("Cleared the local session.")


def _prompt_api() -> tuple[str, str]:
    api_id = input("api_id: ").strip()
    if not api_id.isdigit():
        sys.exit("api_id must be numeric.")
    api_hash = getpass.getpass("api_hash (hidden input): ").strip()
    if len(api_hash) < 20:
        sys.exit("api_hash looks too short; expected a 32-char hex string.")
    return api_id, api_hash


async def setup() -> None:
    print(
        "Telegram credential setup.\n"
        "Values are stored in the macOS Keychain under service 'tgdl'.\n"
        "Get api_id / api_hash at https://my.telegram.org -> API development tools.\n"
    )

    if keyring.get_password(SERVICE, "session"):
        if input("A session already exists. Overwrite? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return

    stored_id = keyring.get_password(SERVICE, "api_id")
    stored_hash = keyring.get_password(SERVICE, "api_hash")
    if stored_id and stored_hash and \
            input(f"Reuse stored api_id {stored_id}? [Y/n] ").strip().lower() in ("", "y", "yes"):
        api_id, api_hash = stored_id, stored_hash
    else:
        api_id, api_hash = _prompt_api()

    phone = input("phone (international format, e.g. +14155550123): ").strip()

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    print("\nConnecting. You will be asked for the login code (and 2FA password if set).")
    # Telethon prompts for the code via input() and the 2FA password via getpass().
    await client.start(phone=phone)

    me = await client.get_me()
    session_str = client.session.save()
    await client.disconnect()

    keyring.set_password(SERVICE, "api_id", api_id)
    keyring.set_password(SERVICE, "api_hash", api_hash)
    keyring.set_password(SERVICE, "session", session_str)

    handle = f"@{me.username}" if me.username else "(no username)"
    print(f"\nLogged in as {me.first_name} {handle}. Credentials saved to Keychain.")
    print("Next:  tgdl get <message-link>")


def main() -> None:
    args = sys.argv[1:]
    if "--reset" in args:
        reset()
        return
    if "--logout" in args:
        asyncio.run(logout())
        return
    asyncio.run(setup())


if __name__ == "__main__":
    main()
