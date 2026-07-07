"""Unit tests for tgdl's pure helpers — no login, network, or Keychain needed.

Run locally:
    uv run --with pytest --with telethon --with keyring --with tqdm pytest -q tests/
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tg_download as td  # noqa: E402


# --- parse_link ------------------------------------------------------------

@pytest.mark.parametrize("link, expected", [
    ("https://t.me/syfls11/352?comment=955", ("username", "syfls11", 352, 955)),
    ("https://t.me/syfls11/352",             ("username", "syfls11", 352, None)),
    ("https://t.me/c/1234567890/42",         ("channel", 1234567890, 42, None)),
    ("https://t.me/c/1234567890/99/42",      ("channel", 1234567890, 42, None)),
    ("https://t.me/some_group/55/678",       ("username", "some_group", 678, None)),
    ("https://t.me/c/1234567890/42?comment=7", ("channel", 1234567890, 42, 7)),
    ("t.me/durov/123",                       ("username", "durov", 123, None)),
    ("https://t.me/syfls11/352?single&comment=955", ("username", "syfls11", 352, 955)),
])
def test_parse_link_ok(link, expected):
    assert td.parse_link(link) == expected


@pytest.mark.parametrize("bad", [
    "https://example.com/foo/1",   # not a Telegram host
    "garbage",
    "https://t.me/onlyname",       # no message id
    "https://t.me/c/123",          # no message id
    "",
])
def test_parse_link_rejects(bad):
    with pytest.raises(ValueError):
        td.parse_link(bad)


# --- sanitize (path-traversal safety) --------------------------------------

def test_sanitize_no_path_separator():
    assert "/" not in td.sanitize("../../etc/passwd.mp4")


def test_sanitize_replaces_spaces():
    assert " " not in td.sanitize("a b c.mp4")


def test_sanitize_caps_length():
    assert len(td.sanitize("x" * 500)) <= 120


@pytest.mark.parametrize("junk", ["!!!", "", "///"])
def test_sanitize_empty_fallback(junk):
    assert td.sanitize(junk) == "file"


# --- build_name ------------------------------------------------------------

def test_build_name_with_original():
    entity = SimpleNamespace(id=999)
    msg = SimpleNamespace(id=42, file=SimpleNamespace(ext=".mp4", name="clip.mp4"))
    assert td.build_name(entity, msg) == "999_42_clip.mp4"


def test_build_name_without_original():
    entity = SimpleNamespace(id=999)
    msg = SimpleNamespace(id=42, file=SimpleNamespace(ext=".mp4", name=None))
    assert td.build_name(entity, msg) == "999_42.mp4"


# --- is_video --------------------------------------------------------------

def test_is_video_video_attr():
    assert td.is_video(SimpleNamespace(video=object())) is True


def test_is_video_document_mime():
    msg = SimpleNamespace(video=None, document=SimpleNamespace(mime_type="video/mp4"))
    assert td.is_video(msg) is True


def test_is_video_rejects_image():
    msg = SimpleNamespace(video=None, document=SimpleNamespace(mime_type="image/png"))
    assert td.is_video(msg) is False


def test_is_video_rejects_none():
    assert td.is_video(SimpleNamespace(video=None, document=None)) is False


# --- _human ----------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1048576, "1.0 MB"),
    (1073741824, "1.0 GB"),
])
def test_human(n, expected):
    assert td._human(n) == expected
