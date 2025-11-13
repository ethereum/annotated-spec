#!/usr/bin/env python3
"""Regenerate annotated specs from upstream, appending local notes where available."""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path
import re
from typing import Dict, Iterator, List

REPO_DIR = Path(__file__).resolve().parents[1]
CONSENSUS_ROOT = REPO_DIR / "consensus-specs"
HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
NOTES_MARK = "<!-- NOTES-BEGIN -->"
IGNORED_TOP_LEVEL = {".git", "consensus-specs", "phase1"}
IGNORED_PATHS = {Path("README.md")}


def slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def run_git(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout


def iter_markdown_files(targets: List[str]) -> Iterator[Path]:
    if targets:
        resolved: List[Path] = []
        for raw in targets:
            path = Path(raw)
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
            if path.is_dir():
                resolved.extend(sorted(path.rglob("*.md")))
            else:
                resolved.append(path)
    else:
        resolved = sorted(Path.cwd().rglob("*.md"))

    seen = set()
    for path in resolved:
        try:
            rel = path.resolve().relative_to(REPO_DIR)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in IGNORED_TOP_LEVEL:
            continue
        if rel in IGNORED_PATHS:
            continue
        abs_path = REPO_DIR / rel
        if abs_path.is_dir():
            continue
        if abs_path in seen:
            continue
        seen.add(abs_path)
        yield abs_path


def collect_notes(text: str) -> Dict[str, List[str]]:
    notes: Dict[str, List[str]] = defaultdict(list)
    matches = list(HEADING_RE.finditer(text))
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[start:end]
        marker_idx = section.find(NOTES_MARK)
        if marker_idx == -1:
            continue
        slug = slugify(match.group(2))
        notes[slug].append(section[marker_idx:])
    return notes


def load_upstream_text(rel_path: Path, commit: str) -> str:
    spec_unix = (Path("specs") / rel_path).as_posix()
    return run_git(
        ["git", "-C", str(CONSENSUS_ROOT), "show", f"{commit}:{spec_unix}"]
    )


def merge_with_notes(upstream: str, notes: Dict[str, List[str]]) -> str:
    matches = list(HEADING_RE.finditer(upstream))
    if not matches:
        return upstream

    output: List[str] = []

    def ensure_blank_line() -> None:
        if not output:
            return
        last = output[-1]
        trailing = len(last) - len(last.rstrip("\n"))
        missing = 2 - trailing if trailing < 2 else 0
        if missing <= 0:
            return
        if trailing == 0 and last:
            output[-1] = last + "\n"
            missing -= 1
        if missing > 0:
            output.append("\n" * missing)
    cursor = 0
    for idx, match in enumerate(matches):
        start = match.start()
        if cursor < start:
            output.append(upstream[cursor:start])

        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(upstream)
        output.append(upstream[start:end])

        slug = slugify(match.group(2))
        slug_notes = notes.get(slug)
        if slug_notes:
            note = slug_notes.pop(0)
            if note:
                ensure_blank_line()
            output.append(note)

        cursor = end

    if cursor < len(upstream):
        output.append(upstream[cursor:])

    return "".join(output)


def bump_file(path: Path, commit: str) -> bool:
    rel_path = path.resolve().relative_to(REPO_DIR)
    annotated_text = path.read_text(encoding="utf-8")
    notes = collect_notes(annotated_text)
    upstream_text = load_upstream_text(rel_path, commit)
    merged = merge_with_notes(upstream_text, notes)
    if merged != annotated_text:
        path.write_text(merged, encoding="utf-8")
        print(f"{rel_path.as_posix()}: updated")
        return True
    print(f"{rel_path.as_posix()}: already current")
    return False


def main(argv: List[str]) -> int:
    if not CONSENSUS_ROOT.exists():
        print(
            "consensus-specs submodule missing; run `git submodule update --init --recursive`.",
            file=sys.stderr,
        )
        return 1
    try:
        commit = run_git(["git", "-C", str(CONSENSUS_ROOT), "rev-parse", "HEAD"]).strip()
    except subprocess.CalledProcessError as exc:
        print(f"sync: {exc}", file=sys.stderr)
        return 1

    targets = list(iter_markdown_files(argv))
    if not targets:
        print("No markdown files found.", file=sys.stderr)
        return 0

    exit_code = 0
    for path in targets:
        try:
            bump_file(path, commit)
        except subprocess.CalledProcessError as exc:
            print(f"{path}: git error: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
