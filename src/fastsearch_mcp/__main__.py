"""Entry point: `fastsearch-mcp` (stdio MCP server) plus maintenance subcommands."""

from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('compare', 'report'):
        try:
            from . import telemetry  # noqa: F401
        except ImportError:
            sys.exit(f"fastsearch-mcp {argv[0]}: not available in the search-only build (no usage records)")
    if argv and argv[0] == 'compare':
        from .compare import generate_comparison
        parser = argparse.ArgumentParser(prog='fastsearch-mcp compare')
        parser.add_argument('--count', type=int, default=5)
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--seed', type=int)
        parser.add_argument('--timeout', type=float, default=30)
        parser.add_argument('--output')
        args = parser.parse_args(argv[1:])
        print(generate_comparison(**vars(args)))
        return
    if argv and argv[0] == "report":
        from .report import write_report
        from .telemetry import db_path
        parser = argparse.ArgumentParser(prog="fastsearch-mcp report")
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--output", default=str(db_path().parent / "reports" / "fastsearch.html"))
        args = parser.parse_args(argv[1:])
        if args.days < 1:
            parser.error("--days must be positive")
        print(write_report(args.output, days=args.days))
        return
    ap = argparse.ArgumentParser(prog="fastsearch-mcp", description="fd + ripgrep MCP server")
    ap.add_argument("--install", action="store_true", help="download fd/rg now (if not on PATH) and exit")
    ap.add_argument("--doctor", action="store_true", help="show which fd/rg binaries will be used and exit")
    ap.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http", "sse"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.install or a.doctor:
        from .binaries import BinaryNotFound, cache_dir, get_binary
        ok = True
        print(f"cache dir: {cache_dir()}")
        for name in ("fd", "rg"):
            try:
                path = get_binary(name, log=lambda m: print(m, file=sys.stderr))
                ver = subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip()
                print(f"{name}: {path}  ({ver.splitlines()[0] if ver else '?'})")
            except BinaryNotFound as e:
                ok = False
                print(f"{name}: NOT AVAILABLE\n  {e}")
        sys.exit(0 if ok else 1)

    from .server import mcp
    if a.transport == "stdio":
        mcp.run()
    else:
        mcp.run(a.transport, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
