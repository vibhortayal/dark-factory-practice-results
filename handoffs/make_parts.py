#!/usr/bin/env python3
"""Assemble a multi-part room handoff from source files.

usage: make_parts.py <handle> <title> <outdir> <label=path>...

Every source file is pasted in full, cut at line boundaries into parts small
enough for one room message. Each part starts with the recipient handle and a
part marker; the last part is marked FINAL.
"""
import pathlib
import sys

LIMIT = 11000


def chunks(text):
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        if cur and len(cur) + len(line) > LIMIT:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def main():
    handle, title, outdir = sys.argv[1:4]
    bodies = []
    for spec in sys.argv[4:]:
        label, path = spec.split("=", 1)
        pieces = chunks(pathlib.Path(path).read_text(encoding="utf-8"))
        for i, piece in enumerate(pieces, 1):
            bodies.append((f"{label} (section {i} of {len(pieces)})", piece))
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    total = len(bodies)
    for n, (label, piece) in enumerate(bodies, 1):
        final = " — FINAL PART" if n == total else ""
        head = f"{handle} {title} — PART {n} of {total}{final} — {label}\n\n"
        (out / f"part-{n:02d}.txt").write_text(head + piece, encoding="utf-8")
    print(total)


if __name__ == "__main__":
    main()
