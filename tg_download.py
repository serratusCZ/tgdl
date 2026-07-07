#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "telethon>=1.36",
#     "cryptg>=0.4",
#     "keyring>=24",
#     "tqdm>=4",
# ]
# ///
"""Download videos from Telegram chats you belong to, including chats that
have "restrict saving content" enabled.

The save restriction is only enforced by the official client UI; the MTProto
API still delivers the media to an authorized user session, so a normal
download works. Only use this for content you are allowed to keep, and
respect copyright and each group's rules.

Credentials are read from the macOS Keychain (populated by `tgdl setup`).

Examples:
    tgdl get https://t.me/c/1234567890/42
    tgdl get https://t.me/somechannel/99 --out ~/Movies/tg
    tgdl get --chat https://t.me/c/1234567890 --range 100 180
    tgdl list
    tgdl check
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

import keyring
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel
from tqdm import tqdm

SERVICE = "tgdl"

# https://t.me/c/<internal_id>/<optional_topic_id>/<msg_id>
LINK_C = re.compile(r"(?:https?://)?t\.me/c/(\d+)/(?:\d+/)?(\d+)")
# https://t.me/<username>/<optional_topic_id>/<msg_id>
LINK_PUB = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,})/(?:\d+/)?(\d+)")


def load_creds() -> tuple[int, str, str]:
    api_id = keyring.get_password(SERVICE, "api_id")
    api_hash = keyring.get_password(SERVICE, "api_hash")
    session = keyring.get_password(SERVICE, "session")
    if not (api_id and api_hash and session):
        sys.exit("No stored credentials. Run:  tgdl setup")
    return int(api_id), api_hash, session


def parse_link(link: str) -> tuple[str, object, int]:
    link = link.strip()
    m = LINK_C.match(link)
    if m:
        return ("channel", int(m.group(1)), int(m.group(2)))
    m = LINK_PUB.match(link)
    if m:
        return ("username", m.group(1), int(m.group(2)))
    raise ValueError(f"Unrecognized Telegram message link: {link}")


async def get_channel(client: TelegramClient, cid: int):
    try:
        return await client.get_entity(PeerChannel(cid))
    except Exception:
        # Populate the entity cache, then retry. Needed the first time a
        # private channel is referenced from a fresh session.
        await client.get_dialogs()
        return await client.get_entity(PeerChannel(cid))


async def resolve_entity(client: TelegramClient, kind: str, ref):
    if kind == "channel":
        return await get_channel(client, int(ref))
    return await client.get_entity(ref)


async def resolve_chat(client: TelegramClient, spec: str):
    """Resolve a --chat argument: c-link, public link, @username or numeric id."""
    spec = spec.strip()
    m = re.search(r"t\.me/c/(\d+)", spec)
    if m:
        return await get_channel(client, int(m.group(1)))
    m = re.search(r"t\.me/([A-Za-z0-9_]{4,})", spec)
    if m:
        return await client.get_entity(m.group(1))
    if spec.lstrip("-").isdigit():
        val = int(spec)
        s = str(val)
        if s.startswith("-100"):
            return await get_channel(client, int(s[4:]))
        try:
            return await client.get_entity(val)
        except Exception:
            await client.get_dialogs()
            return await client.get_entity(val)
    return await client.get_entity(spec.lstrip("@"))


def is_video(msg) -> bool:
    if getattr(msg, "video", None):
        return True
    doc = getattr(msg, "document", None)
    mime = getattr(doc, "mime_type", "") or ""
    return mime.startswith("video/")


def sanitize(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("_")[:120] or "file"


def build_name(entity, msg) -> str:
    ext = (msg.file.ext if msg.file else "") or ".bin"
    orig = getattr(msg.file, "name", None) if msg.file else None
    cid = getattr(entity, "id", "chat")
    if orig:
        return sanitize(f"{cid}_{msg.id}_{orig}")
    return sanitize(f"{cid}_{msg.id}{ext}")


async def download_message(client, entity, msg, out_dir: Path, want_all: bool) -> bool:
    if not getattr(msg, "media", None):
        return False
    if not want_all and not is_video(msg):
        return False

    name = build_name(entity, msg)
    dest = out_dir / name
    size = msg.file.size if msg.file else 0
    if dest.exists() and size and dest.stat().st_size == size:
        print(f"[skip] already downloaded: {name}")
        return True

    desc = (name[:27] + "...") if len(name) > 30 else name
    with tqdm(total=size or 0, unit="B", unit_scale=True, desc=desc, leave=True) as bar:
        def cb(cur, tot):
            if tot:
                bar.total = tot
            bar.n = cur
            bar.refresh()

        path = await client.download_media(msg, file=str(dest), progress_callback=cb)
    print(f"[done] {path}")
    return True


async def run(args) -> None:
    api_id, api_hash, session = load_creds()
    out_dir = Path(args.out or os.environ.get("TGDL_OUT") or "downloads").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            sys.exit("Session invalid or expired. Run:  tgdl setup")

        if args.check:
            me = await client.get_me()
            handle = f"@{me.username}" if me.username else "(no username)"
            print(f"Connected as {me.first_name} {handle}  id={me.id}")
            print(f"Output directory: {out_dir}")
            return

        if args.list:
            async for dialog in client.iter_dialogs():
                print(f"{dialog.id}\t{dialog.name}")
            return

        downloaded = 0

        if args.chat and args.range:
            a, b = args.range
            entity = await resolve_chat(client, args.chat)
            ids = list(range(min(a, b), max(a, b) + 1))
            messages = await client.get_messages(entity, ids=ids)
            for msg in messages:
                if msg is None:
                    continue
                downloaded += await _guarded_download(client, entity, msg, out_dir, args.all)
            print(f"Downloaded {downloaded} file(s) to {out_dir}")
            return

        if not args.targets:
            sys.exit("Nothing to do. Give message link(s), or --chat/--range, or --list.")

        for link in args.targets:
            kind, ref, mid = parse_link(link)
            entity = await resolve_entity(client, kind, ref)
            msg = await client.get_messages(entity, ids=mid)
            if not msg:
                print(f"[skip] message not found: {link}")
                continue
            got = await _guarded_download(client, entity, msg, out_dir, args.all)
            if not got and getattr(msg, "media", None):
                print(f"[skip] not a video: {link} (use --all for any media)")
            downloaded += got
        print(f"Downloaded {downloaded} file(s) to {out_dir}")
    finally:
        await client.disconnect()


async def _guarded_download(client, entity, msg, out_dir, want_all) -> int:
    """Download with FloodWait handling. Returns 1 on success, 0 otherwise."""
    while True:
        try:
            return 1 if await download_message(client, entity, msg, out_dir, want_all) else 0
        except FloodWaitError as e:
            print(f"[wait] rate limited by Telegram, sleeping {e.seconds}s")
            await asyncio.sleep(e.seconds + 1)


def main() -> None:
    p = argparse.ArgumentParser(prog="tgdl", description="Download Telegram videos.")
    p.add_argument("targets", nargs="*", help="one or more t.me message links")
    p.add_argument("--chat", help="chat link / @username / id for --range mode")
    p.add_argument("--range", nargs=2, type=int, metavar=("START", "END"),
                   help="inclusive message-id range (use with --chat)")
    p.add_argument("--out", help="output directory (default: $TGDL_OUT or ./downloads)")
    p.add_argument("--all", action="store_true",
                   help="download any media, not just videos")
    p.add_argument("--list", action="store_true", help="list your chats (id + name)")
    p.add_argument("--check", action="store_true", help="verify the stored session works")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
