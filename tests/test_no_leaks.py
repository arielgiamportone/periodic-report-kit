"""Leak guard.

This test fails if any term of an obfuscated blocklist (company, client, person and
internal-asset names that must never reach this public repository) appears in the working
tree or in the git history. The list is stored base64-encoded so that the guard itself is
not a readable leak, and this file is excluded from the sweep.

Matching rules
--------------
* Text is accent-folded before matching, so ``Jose`` catches ``José``.
* Terms written entirely in upper case (codes such as ``ABCD``) are matched case-sensitively
  as whole words; everything else is matched case-insensitively as a whole word or phrase.
* A term ending in ``*`` is treated as a prefix.
* A small list of allowed sentences (the attribution line of the README) is removed from the
  text before scanning; those are the only places where the company name may appear.
"""

from __future__ import annotations

import base64
import re
import subprocess
import unicodedata
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

_BLOCKLIST_B64 = (
    "SW50ZXJ2YWxvcgpJbnRlcnZhbG9yIERhdGEKSW50ZXJ2YWxvciBDb25zdWx0aW5nIEdyb3VwCmlu"
    "dGVydmFsb3IuZXMKaW50ZXJ2YWxvcnNvZnQKSUNHCkFZVU5EQVRBCmF5dW5kYXRhCklOVkFZVU5U"
    "CklOVEVSVkFMCklOVEVSREFUQQpBc3NldERhdGEKQXNzZXRWaXNpb24KSW52RGF0YQpLQVRIQVJT"
    "SUQKUExVRwpEYXRhU3RhcgpnZXRwbHVnZ2VkCk1lZ2FzaXN0ZW1hcwpNYW5zaXMKQUVOQQpTLk0u"
    "RS4KRVVJUE8KQmFyYWphcwpBZXJvcHVlcnRvIEFkb2xmbyBTdcOhcmV6IE1hZHJpZC1CYXJhamFz"
    "Ck1BRCA2OS8yMwpNQUQ2OS0yMwpNQUQtMTEyCk1BRC0xMTIvMjAyNgpPVDEKT1QxODExNwpPVDE4"
    "Njg0CjE4LjE2OQoxOC42ODAKSU5GLVlZWVktTk5OTgpDUlQtWVlZWS1OTk5OCjNjZXJzZW0KMm9z"
    "ZW0KYWVuYV9jb21lcmNpYWwKU2FuIEJhcnRvbG9tw6kKQXl1bnRhbWllbnRvIGRlIFNhbiBCYXJ0"
    "b2xvbcOpIGRlIFRpcmFqYW5hClRpcmFqYW5hClNCVApGaXJnYXMKWmFtdWRpbwpTYWd1bnRvCk9s"
    "YWJlcnJpYQpMZXpvCkJydWdhcm9sYXMKQWl6YXJuYXphYmFsCk1ldHJvIGRlIE1hZHJpZApEaXB1"
    "dGFjacOzbiBkZSBTb3JpYQpBZ8OobmNpYSBkZSBSZXNpZHVzClNhbGFzIFZJUApBaXIgUm9vbXMK"
    "Q29uc2lnbmFzClRMSQpUaWVuZGFzIFJldGFpbApSZW50YWNhcgpTUyBCYW5jYXJpb3MKRmFybWFj"
    "aWFzClZlbmRpbmcKUGFya2luZ3MKU2FuZHdpY2hlcwpQdWJsaWNpZGFkClNvcG9ydGVzCkFnZW5j"
    "aWFzIGRlIHZpYWplCk15c3RlcnkgU2hvcHBlcgpDSUNPCkFycXVlbwpTVklQCkFJUlIKQ09OUwpU"
    "REEKQUdFTgpDQU1QClJFU1QKVkVORApGQVJNCkJBTkMKUkVOVApQQVJLClRSRVQKVFRMSQpJQ1NB"
    "CklDU0wKSUNTTQpJQ1NQCklDU0MKVDEKVDIKVDMKVDQKVDRTCkp1bGnDoW4KTnVyaWEKQXJpZWwK"
    "QW5ueQpBbGVqYW5kcm8KQWFyw7NuCkZlcm5hbmRvCkNyaXN0aW5hCkJydW5vClZpY3RvcmlhCkV2"
    "YQpBcmllbCBHaWFtcG9ydGUKQzpcVXNlcnMKT25lRHJpdmUKT25lRHJpdmUgLSBJbnRlcnZhbG9y"
    "CklORk9STUUKOTkuIEdFTkVSQURPUwowMC4gUmVwb3J0ZXMgUgpIT1JBUklPUyBZIENPTlRST0wK"
    "Q29udHJvbGVzIG1lcwpUZW1wbGF0ZV9tYXJjYS5kb2N4CnBvcnRhZGFfdGVtcGxhdGVfYmcucG5n"
    "CnBvcnRhZGFfZm9uZG8ucG5nCmtpdF9pbmZvcm1lc19pbnRlcnZhbG9yClJlc3VtZW4gRVhQCklU"
    "RU1TIFBBUkEgSU5GT1JNRVMKcmVwb3J0ZV9wbHVnCl9yZXBvcnRlLnhsc3gKVFJBQkFKTwpDT0RJ"
    "R08KQ0FNUE8gSU5GT1JNRQpURVhUTyBJTkZPUk1FCklOQ0lERU5DSUFTCkFSUkVOREFUQVJJTwpG"
    "RUNIQSBZIEhPUkEKRGV0YWxsZQpIb2phMQpIb2phMgpTaGVldCAxCkNBTVBPX1BMVUcKd29ya190"
    "eXBlCndvcmtfZGF0YQpUSVRQUEFMClRJVFNFQwpURVhQUEFMCiUgZGUgY3VtcGxpbWllbnRvCiUg"
    "ZGUgY29udHJvbGVzIGxpbXBpb3MKIzY1NURDNgojMDBDMURFCiMxQTJBNkMKIzJDM0U1MAojRjVG"
    "Q0ZFCiNGRkYzQ0QKI0RFRTJFNgpTZWdvZSBVSQpzZWdvZXVpCm1hZDY5MjMKaW52ZW50YXJpby1t"
    "dW5pY2lwYWwKYW5hbGlzaXMtYXJlYS1pdApkZW1vX3Bvd2VyYmkKaW5mb3JtZXNfbWFkNjkyMw=="
)

_ALLOWED_B64 = (
    "UGF0cm9uZXMgZGVzYXJyb2xsYWRvcyBkdXJhbnRlIG1pIHRyYWJham8gZW4gSW50ZXJ2YWxvciBE"
    "YXRhIHkgcHVibGljYWRvcyBjb24gYXV0b3JpemFjacOzbi4gSW1wbGVtZW50YWNpw7NuIGluZGVw"
    "ZW5kaWVudGUgKGNsZWFuLXJvb20pIGNvbiBkYXRvcyBzaW50w6l0aWNvczsgbm8gY29udGllbmUg"
    "Y8OzZGlnbyBuaSBkYXRvcyBkZSBsYSBlbXByZXNhIG5pIGRlIHN1cyBjbGllbnRlcy4KUGF0dGVy"
    "bnMgZGV2ZWxvcGVkIGR1cmluZyBteSB3b3JrIGF0IEludGVydmFsb3IgRGF0YSBhbmQgcHVibGlz"
    "aGVkIHdpdGggcGVybWlzc2lvbi4gSW5kZXBlbmRlbnQgY2xlYW4tcm9vbSBpbXBsZW1lbnRhdGlv"
    "biB3aXRoIHN5bnRoZXRpYyBkYXRhOyBpdCBjb250YWlucyBubyBjb2RlIG9yIGRhdGEgZnJvbSB0"
    "aGUgY29tcGFueSBvciBpdHMgY2xpZW50cy4="
)

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".csv",
    ".html",
    ".css",
    ".svg",
    ".xml",
    ".rst",
    ".in",
    ".sh",
    ".bat",
    ".ps1",
    ".tex",
    "",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".typed",
}
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx", ".dotx", ".potx"}


def _decode(blob: str) -> list[str]:
    raw = base64.b64decode(blob).decode("utf-8")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def fold(text: str) -> str:
    """Strip accents (NFKD) but keep case; used for both the text and the terms."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _pattern(term: str) -> re.Pattern[str]:
    prefix = term.endswith("*")
    term = term.rstrip("*")
    body = re.escape(fold(term))
    lead = r"(?<![A-Za-z0-9])" if term[0].isalnum() else ""
    trail = "" if prefix else (r"(?![A-Za-z0-9])" if term[-1].isalnum() else "")
    flags = 0 if (term.isupper() and term.replace(" ", "").isalpha()) else re.IGNORECASE
    return re.compile(lead + body + trail, flags)


def compile_blocklist() -> list[tuple[str, re.Pattern[str]]]:
    return [(t, _pattern(t)) for t in _decode(_BLOCKLIST_B64)]


def scrub_allowed(text: str) -> str:
    for sentence in _decode(_ALLOWED_B64):
        text = text.replace(fold(sentence), " ")
    return text


def find_leaks(text: str, blocklist: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    folded = scrub_allowed(fold(text))
    hits: list[str] = []
    for term, pattern in blocklist:
        if pattern.search(folded):
            hits.append(term)
    return hits


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, errors="replace"
    )
    return out.stdout


def tracked_and_untracked_files() -> list[Path]:
    listing = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = [ROOT / p for p in listing.split("\0") if p]
    return [p for p in paths if p.is_file() and p.resolve() != SELF]


def read_text_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in OFFICE_SUFFIXES:
        parts: list[str] = []
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith((".xml", ".rels", ".txt")):
                    parts.append(zf.read(name).decode("utf-8", errors="replace"))
        return "\n".join(parts)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    # Binary assets (png, ttf, pdf...): scan the raw bytes decoded leniently so that embedded
    # metadata strings are still checked.
    return path.read_bytes().decode("latin-1", errors="replace")


@pytest.fixture(scope="module")
def blocklist() -> list[tuple[str, re.Pattern[str]]]:
    terms = compile_blocklist()
    assert len(terms) > 100, "the blocklist looks truncated"
    return terms


def test_matching_rules_behave_as_documented() -> None:
    bl = [(t, _pattern(t)) for t in ("ABCD", "Zelmira", "foo-*", "x.y")]
    assert find_leaks("code abcd lower", bl) == []
    assert find_leaks("code ABCD upper", bl) == ["ABCD"]
    assert find_leaks("zelmíra appears", bl) == ["Zelmira"]
    assert find_leaks("zelmiraville is a different word", bl) == []
    assert find_leaks("foo-anything matches the prefix", bl) == ["foo-*"]
    assert find_leaks("x.y matches but x_y does not", bl) == ["x.y"]


def test_working_tree_has_no_forbidden_terms(blocklist) -> None:
    offenders: dict[str, list[str]] = {}
    for path in tracked_and_untracked_files():
        hits = find_leaks(read_text_of(path), blocklist)
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, f"forbidden terms found: {offenders}"


def test_git_history_has_no_forbidden_terms(blocklist) -> None:
    rel_self = SELF.relative_to(ROOT).as_posix()
    log = _git("log", "-p", "--all", "--", ".", f":(exclude){rel_self}")
    hits = find_leaks(log, blocklist)
    assert not hits, f"forbidden terms found in git history: {hits}"
