"""Self-contained public MCP executable and credential-safe setup entry point."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="PlugLayer public connector (bundled runtime)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--setup-url")
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--command-safety-hook", action="store_true")
    modes.add_argument("--upgrade", nargs=3, metavar=("TARGET", "VERSION", "COMMIT"))
    parser.add_argument("--test-home", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.self_test:
            from pluglayer_mcp.native_health import build_info, tool_names
            info = build_info()
            names = asyncio.run(tool_names())
            if info["tools"] and names != info["tools"]:
                raise RuntimeError("Bundled public tool inventory is incomplete")
            print(json.dumps({"release": info["release"], "tools": names}))
        elif args.command_safety_hook:
            import runpy
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
            script = root / "native-hooks/command_safety_hook.py" if getattr(sys, "frozen", False) else root / "plugins/pluglayer-antigravity-plugin/scripts/command_safety_hook.py"
            runpy.run_path(str(script), run_name="__main__")
        elif args.doctor:
            from pluglayer_mcp.native_health import doctor
            print(json.dumps(doctor()))
        elif args.setup_url:
            from pluglayer_mcp.native_health import build_info
            from pluglayer_mcp.native_setup import run_setup
            if args.test_home:
                import os
                from urllib.parse import urlsplit
                if os.environ.get("PLUGLAYER_ALLOW_LOCAL_SETUP") != "1" or urlsplit(args.setup_url).hostname not in {"localhost", "127.0.0.1"}:
                    raise ValueError("A test home is only supported by a local fixture server")
            print(json.dumps(run_setup(args.setup_url, executable=Path(sys.executable).resolve(), build=build_info(), home=args.test_home)))
        elif args.upgrade:
            from pluglayer_mcp.native_upgrade import upgrade
            upgrade(*args.upgrade)
        else:
            from pluglayer_mcp.server import main as serve
            serve()
        return 0
    except Exception as error:
        # Exception strings may contain server responses or secrets. Emit safe
        # categories only; never dump an HTTP exception, argv, or credential file.
        print(f"PlugLayer setup failed ({type(error).__name__}). Existing settings were restored when changed. "
              "Check OS installation permissions, or copy a new setup prompt from the portal.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
