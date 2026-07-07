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
    tgdl get https://t.me/somechannel/352?comment=955   # video in a comment
    tgdl get --chat https://t.me/c/1234567890 --range 100 180
    tgdl list
    tgdl check
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import keyring
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ServerError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import PeerChannel
from tqdm import tqdm

SERVICE = "tgdl"
__version__ = "0.3.0"
# Telegram serves file parts on 4 KiB boundaries; resume offsets must align to it.
CHUNK_ALIGN = 4096
# Transient failures worth retrying; the .part resume makes each retry cheap.
TRANSIENT_ERRORS = (OSError, asyncio.TimeoutError, ServerError)
MAX_RETRIES = 5

TG_HOSTS = ("t.me", "telegram.me", "telegram.dog")


def load_creds() -> tuple[int, str, str]:
    api_id = keyring.get_password(SERVICE, "api_id")
    api_hash = keyring.get_password(SERVICE, "api_hash")
    session = keyring.get_password(SERVICE, "session")
    if not (api_id and api_hash and session):
        sys.exit("No stored credentials. Run:  tgdl setup")
    return int(api_id), api_hash, session


def parse_link(link: str) -> tuple[str, object, int, int | None]:
    """Return (kind, ref, msg_id, comment_id).

    kind is "channel" (ref = internal id from /c/<id>) or "username" (ref = name).
    comment_id is set for links like .../352?comment=955, where the media lives
    in the channel's linked discussion group rather than in post 352 itself.
    """
    link = link.strip()
    u = urlparse(link if "://" in link else "https://" + link)
    if u.netloc.lower() not in TG_HOSTS:
        raise ValueError(f"Unrecognized Telegram message link: {link}")

    comment = None
    q = parse_qs(u.query)
    if "comment" in q:
        try:
            comment = int(q["comment"][0])
        except (ValueError, IndexError):
            comment = None

    parts = [p for p in u.path.split("/") if p]
    # /c/<internal_id>/[<topic_id>/]<msg_id>
    if len(parts) >= 3 and parts[0] == "c" and parts[1].isdigit() and parts[-1].isdigit():
        return ("channel", int(parts[1]), int(parts[-1]), comment)
    # /<username>/[<topic_id>/]<msg_id>
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9_]{4,}", parts[0]) and parts[-1].isdigit():
        return ("username", parts[0], int(parts[-1]), comment)
    raise ValueError(f"Unrecognized Telegram message link: {link}")


async def get_discussion_group(client: TelegramClient, channel):
    """Resolve the discussion supergroup linked to a channel (where comments live)."""
    full = await client(GetFullChannelRequest(channel=channel))
    linked_id = getattr(full.full_chat, "linked_chat_id", None)
    if not linked_id:
        raise ValueError("channel has no linked discussion group (no comments to fetch)")
    for chat in full.chats:
        if chat.id == linked_id:
            return chat
    return await client.get_entity(linked_id)


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


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def build_name(entity, msg) -> str:
    ext = (msg.file.ext if msg.file else "") or ".bin"
    orig = getattr(msg.file, "name", None) if msg.file else None
    cid = getattr(entity, "id", "chat")
    if orig:
        return sanitize(f"{cid}_{msg.id}_{orig}")
    return sanitize(f"{cid}_{msg.id}{ext}")


async def download_message(client, entity, msg, out_dir: Path, want_all: bool,
                           dry_run: bool = False) -> bool:
    if not getattr(msg, "media", None):
        return False
    if not want_all and not is_video(msg):
        return False

    name = build_name(entity, msg)
    dest = out_dir / name
    part = dest.with_name(dest.name + ".part")
    size = msg.file.size if msg.file else 0

    if dry_run:
        if dest.exists() and size and dest.stat().st_size == size:
            print(f"[dry-run] have  {name}")
            return False
        print(f"[dry-run] get   {name}  ({_human(size)})")
        return True

    # Nothing to do if a complete file already exists.
    if dest.exists() and size and dest.stat().st_size == size:
        print(f"[skip] already downloaded: {name}")
        return True
    # A .part left fully downloaded by a previous run: just promote it.
    if part.exists() and size and part.stat().st_size == size:
        part.replace(dest)
        print(f"[done] {dest}")
        return True

    desc = (name[:27] + "...") if len(name) > 30 else name

    if not size:
        # Unknown size (rare for video): plain, non-resumable download.
        with tqdm(unit="B", unit_scale=True, desc=desc, leave=True) as bar:
            def cb(cur, tot):
                if tot:
                    bar.total = tot
                bar.n = cur
                bar.refresh()

            await client.download_media(msg, file=str(part), progress_callback=cb)
        part.replace(dest)
        print(f"[done] {dest}")
        return True

    # Resume: continue from the aligned end of any existing .part, discarding a
    # possibly-truncated trailing chunk so re-requested bytes line up exactly.
    have = part.stat().st_size if part.exists() else 0
    offset = (have // CHUNK_ALIGN) * CHUNK_ALIGN if have < size else 0
    resumed = offset > 0

    with tqdm(total=size, initial=offset, unit="B", unit_scale=True, desc=desc, leave=True) as bar:
        with open(part, "r+b" if part.exists() else "wb") as fh:
            fh.seek(offset)
            fh.truncate()
            async for chunk in client.iter_download(msg.media, offset=offset):
                fh.write(chunk)
                bar.update(len(chunk))

    final = part.stat().st_size
    if final != size:
        print(f"[warn] size mismatch for {name}: got {final}, expected {size}; kept {part.name}")
        return False
    part.replace(dest)
    print(f"[done] {dest}" + (f" (resumed from {offset:,} B)" if resumed else ""))
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
        verb = "Would download" if args.dry_run else "Downloaded"
        tail = "" if args.dry_run else f" to {out_dir}"

        if args.chat and args.range:
            a, b = args.range
            entity = await resolve_chat(client, args.chat)
            ids = list(range(min(a, b), max(a, b) + 1))
            messages = await client.get_messages(entity, ids=ids)
            for msg in messages:
                if msg is None:
                    continue
                downloaded += await _guarded_download(
                    client, entity, msg, out_dir, args.all, args.dry_run)
            print(f"{verb} {downloaded} file(s){tail}")
            return

        if not args.targets:
            sys.exit("Nothing to do. Give message link(s), or --chat/--range, or --list.")

        for link in args.targets:
            try:
                kind, ref, mid, comment = parse_link(link)
                entity = await resolve_entity(client, kind, ref)
                if comment is not None:
                    # The video is in a channel comment -> fetch it from the
                    # linked discussion group, where its id is the comment id.
                    entity = await get_discussion_group(client, entity)
                    mid = comment
            except ValueError as e:
                print(f"[skip] {e}")
                continue
            msg = await client.get_messages(entity, ids=mid)
            if not msg:
                print(f"[skip] message not found: {link}")
                continue
            got = await _guarded_download(
                client, entity, msg, out_dir, args.all, args.dry_run)
            if not got and not args.dry_run and getattr(msg, "media", None):
                print(f"[skip] not a video: {link} (use --all for any media)")
            downloaded += got
        print(f"{verb} {downloaded} file(s){tail}")
    finally:
        await client.disconnect()


async def _guarded_download(client, entity, msg, out_dir, want_all, dry_run=False) -> int:
    """Download with FloodWait + transient-error retry. Returns 1 on success.

    A retried download resumes from its .part file, so re-attempts are cheap.
    """
    attempt = 0
    while True:
        try:
            ok = await download_message(client, entity, msg, out_dir, want_all, dry_run)
            return 1 if ok else 0
        except FloodWaitError as e:
            print(f"[wait] rate limited by Telegram, sleeping {e.seconds}s")
            await asyncio.sleep(e.seconds + 1)
        except TRANSIENT_ERRORS as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                print(f"[error] giving up after {MAX_RETRIES} retries: {type(e).__name__}: {e}")
                return 0
            backoff = min(2 ** attempt, 30)
            print(f"[retry {attempt}/{MAX_RETRIES}] {type(e).__name__}; resuming in {backoff}s")
            await asyncio.sleep(backoff)


def main() -> None:
    p = argparse.ArgumentParser(prog="tgdl", description="Download Telegram videos.")
    p.add_argument("targets", nargs="*", help="one or more t.me message links")
    p.add_argument("--chat", help="chat link / @username / id for --range mode")
    p.add_argument("--range", nargs=2, type=int, metavar=("START", "END"),
                   help="inclusive message-id range (use with --chat)")
    p.add_argument("--out", help="output directory (default: $TGDL_OUT or ./downloads)")
    p.add_argument("--all", action="store_true",
                   help="download any media, not just videos")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would be downloaded without downloading")
    p.add_argument("--list", action="store_true", help="list your chats (id + name)")
    p.add_argument("--check", action="store_true", help="verify the stored session works")
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="-v for info, -vv for debug (Telethon) logging")
    p.add_argument("--version", action="version", version=f"tgdl {__version__}")
    args = p.parse_args()

    level = (logging.DEBUG if args.verbose >= 2
             else logging.INFO if args.verbose == 1
             else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
