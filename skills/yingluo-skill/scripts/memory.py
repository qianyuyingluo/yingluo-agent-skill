#!/usr/bin/env python3
"""JSON CLI for Yingluo experience memory (Python standard library only)."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import review
import store

MAX_INPUT = 1024 * 1024


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    if path == "-":
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
    else:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("JSON input exceeds 1 MiB; split large reviews into a smaller database scope")
    def invalid_constant(_):
        raise ValueError("non-finite JSON numbers are not supported")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def parser():
    p = Parser(description=__doc__)
    p.add_argument("--db", default=os.environ.get("YINGLUO_MEMORY_DB"),
                   help="persistent SQLite path (or YINGLUO_MEMORY_DB)")
    subs = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("init", "status"):
        subs.add_parser(name)
    for name in ("add", "outcome", "review"):
        subs.add_parser(name).add_argument("--file", required=True, help="UTF-8 JSON path, or - for stdin")
    q = subs.add_parser("search")
    q.add_argument("--query", required=True)
    q.add_argument("--project")
    q.add_argument("--tag", action="append", default=[])
    q.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    q.add_argument("--limit", type=int, default=5)
    subs.add_parser("show").add_argument("--id", required=True, type=int)
    subs.add_parser("review-plan").add_argument("--include-archived", action="store_true")
    return p


def run(args):
    if not args.db or not args.db.strip():
        raise ValueError("set --db or YINGLUO_MEMORY_DB to a persistent database path")
    if args.db == ":memory:":
        raise ValueError("use a persistent file, not :memory:")
    payload = load_json(args.file) if hasattr(args, "file") else None
    with store.connect(args.db, initialize=args.command == "init") as db:
        if args.command in ("init", "status"):
            return store.status(db)
        if args.command == "add":
            return store.add(db, payload)
        if args.command == "outcome":
            return store.record_outcome(db, payload)
        if args.command == "review":
            return review.apply(db, payload)
        if args.command == "show":
            return store.show(db, args.id)
        if args.command == "review-plan":
            return review.plan(db, args.include_archived)
        env = {}
        for item in args.env:
            key, separator, value = item.partition("=")
            if not separator or not key.strip() or not value.strip() or key in env:
                raise ValueError("each --env must have a unique KEY=VALUE")
            env[key] = value
        return {"matches": store.search(db, args.query, args.project, args.tag, env, args.limit)}


def main(argv=None):
    try:
        result = {"ok": True, **run(parser().parse_args(argv))}
        code = 0
    except (ValueError, OSError, sqlite3.Error, RecursionError) as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
