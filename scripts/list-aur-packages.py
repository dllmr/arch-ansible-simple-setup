#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""List explicitly-installed AUR packages, their purpose and (best-effort) last use.

"Directly installed" means packages that are *foreign* (not in any sync repo, i.e.
from the AUR or otherwise built locally) AND were installed explicitly rather than
pulled in as a dependency. That is exactly what `pacman -Qem` reports.

The "last used" column is a heuristic. There is no record on Arch of when a program
was last run, so we approximate it with the most recent access time (atime) of the
package's executable files (anything under a .../bin/ directory or marked executable).
Caveats:
  * The root filesystem is usually mounted `relatime`, so atime only advances once per
    24h after a read -- treat the value as "used around this date", not exact.
  * Filesystems mounted `noatime` record nothing; such packages show "unknown".
  * Background/library packages with no executable also show "unknown".
Use it to surface obvious never/rarely-used candidates, not as proof of disuse.
"""

import argparse
import csv
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def run(args: list[str]) -> str:
    """Run a command and return stdout, raising a friendly error on failure."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        sys.exit(f"error: '{args[0]}' not found -- is this an Arch-based system?")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"error: {' '.join(args)} failed:\n{exc.stderr.strip()}")
    return proc.stdout


def try_run(args: list[str]) -> str | None:
    """Run a command, returning stdout or None on any failure (non-fatal)."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout


def explicit_aur_packages() -> list[str]:
    """Names of explicitly-installed foreign (AUR/local) packages."""
    return sorted(run(["pacman", "-Qemq"]).split())


def package_info(names: list[str]) -> dict[str, dict[str, str]]:
    """Parse `pacman -Qi` blocks into {name: {field: value}}."""
    out = run(["pacman", "-Qi", *names])
    info: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    last_key = ""
    for line in out.splitlines():
        if not line.strip():
            if current.get("Name"):
                info[current["Name"]] = current
            current, last_key = {}, ""
            continue
        if line[0].isspace() and last_key:  # continuation of previous field
            current[last_key] += " " + line.strip()
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        current[key], last_key = value, key
    if current.get("Name"):
        info[current["Name"]] = current
    return info


def package_files(names: list[str]) -> dict[str, list[Path]]:
    """Map each package to its owned file paths via a single `pacman -Ql` call."""
    out = run(["pacman", "-Ql", *names])
    files: dict[str, list[Path]] = {n: [] for n in names}
    for line in out.splitlines():
        name, _, path = line.partition(" ")
        if name in files:
            files[name].append(Path(path))
    return files


def last_used(paths: list[Path]) -> datetime | None:
    """Most recent atime across a package's executable files, or None."""
    newest: float | None = None
    for path in paths:
        # Restrict to runnable things: in a bin dir, or with an exec bit set.
        if "/bin/" not in str(path) and "/sbin/" not in str(path):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        if newest is None or st.st_atime > newest:
            newest = st.st_atime
    if newest is None:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc).astimezone()


# --- Flathub matching -------------------------------------------------------

# Suffixes that distinguish a build variant rather than the software itself.
_PKG_SUFFIXES = (
    "-bin", "-git", "-stable", "-beta", "-nightly", "-debug", "-appimage",
    "-electron", "-desktop", "-kde6", "-qt", "-gtk", "-common",
)


def _collapse(text: str) -> str:
    """Lowercase, keep only alphanumerics -- for fuzzy name comparison."""
    return "".join(c for c in text.lower() if c.isalnum())


def normalize_pkg(name: str) -> tuple[str, str]:
    """Return (hyphenated, collapsed) forms with build-variant suffixes removed."""
    base = name.lower()
    changed = True
    while changed:
        changed = False
        for suffix in _PKG_SUFFIXES:
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[: -len(suffix)]
                changed = True
    return base, _collapse(base)


def fetch_flathub() -> list[tuple[str, str]]:
    """(app_id, name) pairs for every app on Flathub, or [] if unavailable.

    flathub may be registered under the system and/or user installation, which
    makes a bare `remote-ls` ambiguous, so we try both scopes explicitly.
    """
    for scope in ("--system", "--user", None):
        args = ["flatpak", "remote-ls", "flathub", "--app",
                "--columns=application,name"]
        if scope:
            args.insert(2, scope)
        out = try_run(args)
        if not out:
            continue
        entries = []
        for line in out.splitlines():
            app_id, _, name = line.partition("\t")
            if app_id and "." in app_id:  # skip prompt/noise lines
                entries.append((app_id.strip(), name.strip()))
        if entries:
            return entries
    return []


def match_flathub(name: str, entries: list[tuple[str, str]]) -> str:
    """Best-guess Flathub app id for an AUR package, '' if none.

    A trailing '?' flags a fuzzy (substring) match worth eyeballing.
    """
    _, pc = normalize_pkg(name)
    if not pc:
        return ""
    best: tuple[int, int, str] | None = None  # (rank, len(id), app_id)
    for app_id, app_name in entries:
        segments = [_collapse(s) for s in app_id.lower().split(".")]
        nc = _collapse(app_name)
        if pc in segments:            # e.g. 'spotify' in com.spotify.Client
            rank = 0
        elif nc == pc:                # display name matches exactly
            rank = 1
        elif len(pc) >= 4 and (pc in nc or nc in pc):
            rank = 2
        elif len(pc) >= 5 and pc in _collapse(app_id):
            rank = 3
        else:
            continue
        cand = (rank, len(app_id), app_id)
        if best is None or cand < best:  # lower rank, then shorter id, wins
            best = cand
    if best is None:
        return ""
    app_id = best[2]
    return app_id + ("?" if best[0] >= 2 else "")


def parse_install_date(value: str) -> datetime | None:
    """Parse pacman's localized 'Install Date' string; tolerant of locale formats."""
    for fmt in ("%a %d %b %Y %H:%M:%S %Z", "%a %d %b %Y %I:%M:%S %p %Z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# --- AUR last-update lookup -------------------------------------------------

AUR_RPC = "https://aur.archlinux.org/rpc/v5/info"


def fetch_aur_updated(names: list[str]) -> dict[str, datetime]:
    """Map package name -> date it was last updated in the AUR.

    Uses the AUR RPC 'info' endpoint (batched, as it caps args per request).
    Packages absent from the result are not on the AUR -- locally built, dropped,
    or since moved into the official repos. Returns {} if the AUR is unreachable.
    """
    result: dict[str, datetime] = {}
    for start in range(0, len(names), 100):
        chunk = names[start : start + 100]
        query = urllib.parse.urlencode([("arg[]", n) for n in chunk])
        req = urllib.request.Request(
            f"{AUR_RPC}?{query}",
            headers={"User-Agent": "list-aur-packages (https://aur.archlinux.org)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue  # offline or a bad batch -- leave those columns blank
        for pkg in data.get("results", []):
            name, ts = pkg.get("Name"), pkg.get("LastModified")
            if name and ts:
                result[name] = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return result


def collect(check_flathub: bool = True, check_aur: bool = True) -> list[dict]:
    names = explicit_aur_packages()
    if not names:
        return []
    info = package_info(names)
    files = package_files(names)
    flathub = fetch_flathub() if check_flathub else []
    aur = fetch_aur_updated(names) if check_aur else {}
    rows = []
    for name in names:
        meta = info.get(name, {})
        used = last_used(files.get(name, []))
        updated = aur.get(name)
        rows.append(
            {
                "name": name,
                "version": meta.get("Version", "?"),
                "description": meta.get("Description", ""),
                "installed": meta.get("Install Date", ""),
                "last_used": used.strftime("%Y-%m-%d") if used else "",
                "aur_updated": updated.strftime("%Y-%m-%d") if updated else "",
                "flathub": match_flathub(name, flathub) if flathub else "",
                "_sort": used.timestamp() if used else -1.0,
            }
        )
    # Oldest / never-used first -- those are the removal candidates.
    rows.sort(key=lambda r: r["_sort"])
    return rows


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No explicitly-installed AUR packages found.")
        return
    name_w = max(len(r["name"]) for r in rows)
    has_aur = any(r["aur_updated"] for r in rows)
    aur_header = f"  {'AUR UPDATED':<11}" if has_aur else ""
    has_flathub = any(r["flathub"] for r in rows)
    fh_w = max([len(r["flathub"]) for r in rows] + [len("FLATHUB")])
    fh_header = f"  {'FLATHUB':<{fh_w}}" if has_flathub else ""
    header = f"{'PACKAGE':<{name_w}}  {'LAST USED':<10}{aur_header}{fh_header}  PURPOSE"
    print(header)
    print("-" * len(header))
    for r in rows:
        last = r["last_used"] or "unknown"
        au = f"  {(r['aur_updated'] or 'not on AUR'):<11}" if has_aur else ""
        fh = f"  {r['flathub']:<{fh_w}}" if has_flathub else ""
        print(f"{r['name']:<{name_w}}  {last:<10}{au}{fh}  {r['description']}")
    print(f"\n{len(rows)} explicitly-installed AUR packages.")
    if has_flathub:
        n = sum(1 for r in rows if r["flathub"])
        print(f"{n} have a likely Flathub equivalent ('?' = fuzzy match, verify it).")
    print(
        "Note: 'last used' is the newest access time of the package's binaries "
        "(relatime-approximate); 'unknown' = no executable or atime disabled."
    )
    if has_aur:
        print(
            "'AUR updated' is the package's last AUR modification; a stale date can "
            "signal an abandoned package. 'not on AUR' = locally built or dropped."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="output format (default: table)",
    )
    parser.add_argument(
        "--no-flathub",
        action="store_true",
        help="skip the Flathub availability lookup (faster / works offline)",
    )
    parser.add_argument(
        "--no-aur",
        action="store_true",
        help="skip the AUR last-update lookup (faster / works offline)",
    )
    args = parser.parse_args()

    rows = collect(check_flathub=not args.no_flathub, check_aur=not args.no_aur)
    for r in rows:
        r.pop("_sort", None)

    if args.format == "json":
        json.dump(rows, sys.stdout, indent=2)
        print()
    elif args.format == "csv":
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=["name", "version", "last_used", "aur_updated", "flathub",
                        "installed", "description"],
        )
        writer.writeheader()
        writer.writerows(rows)
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
