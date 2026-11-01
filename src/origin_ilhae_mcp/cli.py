"""명령줄 진입점.

  origin-ilhae-mcp              MCP 서버 실행(stdio) — Claude Desktop/Code 가 호출
  origin-ilhae-mcp doctor       연결·한글 처리 점검
  origin-ilhae-mcp install      브리지 파일 설치 + (선택) Claude Desktop 설정 등록
  origin-ilhae-mcp config       MCP 설정 예시 출력
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from importlib import resources
from pathlib import Path

BRIDGE_FILES = ("ilhae_protocol.py", "ilhae_ops.py", "ilhae_bridge.py", "ilhae_start.py", "ilhae_poc.py")


def _utf8_console() -> None:
    # 한국어 Windows 콘솔(CP949)에서 한글·기호 출력이 깨지거나 예외가 나지 않게 한다
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def default_bridge_dir() -> Path:
    return Path.home() / "Documents" / "OriginLab" / "User Files" / "origin-ilhae"


def server_entry() -> dict:
    exe = shutil.which("origin-ilhae-mcp")
    if exe:
        return {"command": exe, "args": []}
    return {"command": "uvx", "args": ["origin-ilhae-mcp"]}


def config_snippet(roots: list[str] | None = None) -> dict:
    entry = server_entry()
    env = {"PYTHONUTF8": "1", "ILHAE_TOOLSETS": "core,korea,physics"}
    if roots:
        env["ILHAE_ALLOWED_ROOTS"] = os.pathsep.join(roots)
    return {"mcpServers": {"origin-ilhae": {**entry, "env": env}}}


def cmd_config(args: argparse.Namespace) -> int:
    snip = config_snippet(args.root)
    print("■ Claude Desktop (claude_desktop_config.json):")
    print(json.dumps(snip, ensure_ascii=False, indent=2))
    entry = snip["mcpServers"]["origin-ilhae"]
    envs = " ".join(f"-e {k}={v}" for k, v in entry["env"].items())
    print("\n■ Claude Code:")
    print(f"claude mcp add origin-ilhae {envs} -- {entry['command']} {' '.join(entry['args'])}".rstrip())
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    target = Path(args.dir) if args.dir else default_bridge_dir()
    target.mkdir(parents=True, exist_ok=True)
    pkg = resources.files("origin_ilhae_mcp") / "bridge"
    for name in BRIDGE_FILES:
        (target / name).write_bytes((pkg / name).read_bytes())
    start = target / "ilhae_start.py"
    print(f"[1/3] 브리지 파일 설치: {target}")
    print("[2/3] Origin 스크립트 창(창 > 스크립트 창)에 아래 한 줄을 붙여 넣고 Enter:")
    print(f'      run -pyf "{start}";')
    print("      (중지: run -py \"import ilhae_bridge; ilhae_bridge.stop()\";)")
    poc = target / "ilhae_poc.py"
    print(f'      Phase 0 실기 검증: run -pyf "{poc}";')
    if args.claude_desktop:
        appdata = os.environ.get("APPDATA")
        cfg = Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else \
            Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        data = {}
        if cfg.exists():
            backup = cfg.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(cfg, backup)
            data = json.loads(cfg.read_text(encoding="utf-8") or "{}")
            print(f"      기존 설정 백업: {backup}")
        data.setdefault("mcpServers", {})["origin-ilhae"] = config_snippet(args.root)["mcpServers"]["origin-ilhae"]
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[3/3] Claude Desktop 설정 등록: {cfg} (Claude Desktop 재시작 필요)")
    else:
        print("[3/3] Claude 등록 방법은 'origin-ilhae-mcp config' 로 확인하세요(--claude-desktop 으로 자동 등록).")
    print("\n브리지를 시작한 뒤 'origin-ilhae-mcp doctor' 로 점검하세요.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .app import App
    from .config import Settings
    from .errors import IlhaeError

    s = Settings.from_env()
    app = App(s)
    print(f"Python {sys.version.split()[0]} / 플랫폼 {sys.platform} / 백엔드 설정 {s.backend}")
    print(f"허용 폴더: {', '.join(str(r) for r in s.allowed_roots)}")
    try:
        ping = app.call("ping", timeout=15)
    except IlhaeError as e:
        print(f"✗ Origin 연결 실패: {e.message}")
        for a in e.next_actions:
            print(f"  → {a}")
        if e.detail:
            print(f"  상세: {json.dumps(e.detail, ensure_ascii=False)}")
        return 2
    print(f"✓ Origin {ping.get('origin_release')} (내장 Python {ping.get('python')}) — 경로: {app.backend.name}")
    if args.skip_korean:
        return 0
    base = Path(args.workdir) if args.workdir else s.allowed_roots[0] / "origin-ilhae-doctor"
    base.mkdir(parents=True, exist_ok=True)
    kr = app.call("kr_roundtrip", timeout=120, workdir=str(base))
    for c in kr["checks"]:
        mark = "✓" if c["ok"] else "✗"
        extra = "" if c["ok"] else f"  (기대: {c['expected']!r}, 실제: {c['actual']!r}) {c.get('note', '')}"
        print(f"  {mark} {c['name']}{extra}")
    path_check = next((c for c in kr["checks"] if c["name"] == "export_korean_path"), None)
    app.save_state(kr_path_ok=bool(path_check and path_check["ok"]), last_doctor=ping.get("origin_release"))
    print("결과:", "모든 한글 시험 통과" if kr["all_ok"] else "일부 실패 — docs/설계서.md 'Phase 0 검증 항목' 참고")
    return 0 if kr["all_ok"] else 1


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(prog="origin-ilhae-mcp", description="Origin 일해 MCP")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="MCP 서버 실행(stdio, 기본)")
    d = sub.add_parser("doctor", help="연결·한글 처리 점검")
    d.add_argument("--workdir", help="한글 경로 시험 폴더")
    d.add_argument("--skip-korean", action="store_true")
    i = sub.add_parser("install", help="브리지 설치")
    i.add_argument("--dir", help=f"설치 폴더(기본: {default_bridge_dir()})")
    i.add_argument("--claude-desktop", action="store_true", help="Claude Desktop 설정에 자동 등록")
    i.add_argument("--root", action="append", help="허용 폴더(여러 번 지정 가능)")
    c = sub.add_parser("config", help="MCP 설정 예시 출력")
    c.add_argument("--root", action="append", help="허용 폴더(여러 번 지정 가능)")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "install":
        return cmd_install(args)
    if args.cmd == "config":
        return cmd_config(args)
    from .server import build_server

    build_server().run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
