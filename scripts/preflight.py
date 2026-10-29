#!/usr/bin/env python3
"""
启动前体检（preflight）
=======================
Docker Compose 的 bind mount 有个静默陷阱：**源路径不存在时，Docker 会替你建一个空目录**。
于是 `backend/.env` 会变成目录，`env_file` 直接报 "is a directory"；uploads/data 被误移后，
容器照常启动，只是上传的文件写进了一个新目录，表现为"文件丢了"。

这个脚本在 `docker compose up` 之前把这类问题显式暴露出来，并顺手补建正常目录。

用法：
    python scripts/preflight.py           # 只检查，不改动
    python scripts/preflight.py --fix     # 补建缺失目录；删除"空的 .env 目录"

退出码：0=可以启动，1=存在必须人工处理的问题。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 工程根目录 = 本文件的上一级
ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = [
    ROOT / "backend" / "uploads",
    ROOT / "backend" / "data",
]
ENV_FILE = ROOT / "backend" / ".env"
ENV_EXAMPLE = ROOT / "backend" / ".env.example"

problems: list[str] = []
notes: list[str] = []


def check_env(fix: bool) -> None:
    if ENV_FILE.is_dir():
        if any(ENV_FILE.iterdir()):
            problems.append(
                "backend/.env 是一个【非空目录】，不是文件。\n"
                "     Docker 曾把它当成挂载点建了目录。请先备份内容后删除该目录，"
                "再执行：cp backend/.env.example backend/.env"
            )
        elif fix:
            ENV_FILE.rmdir()
            notes.append("已删除空的 backend/.env 目录")
        else:
            problems.append(
                "backend/.env 是一个【空目录】（Docker 自动创建）。\n"
                "     处理：rmdir backend/.env && cp backend/.env.example backend/.env\n"
                "     或者重跑本脚本并加 --fix 自动删除该空目录。"
            )
    elif not ENV_FILE.exists():
        problems.append(
            "backend/.env 不存在。\n"
            "     处理：cp backend/.env.example backend/.env，然后填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"
        )
    else:
        raw = ENV_FILE.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            notes.append("backend/.env 带 UTF-8 BOM，建议去掉（首个配置键可能被污染）")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(
                "backend/.env 不是合法的 UTF-8（很可能是 GBK 存盘或双重编码）。\n"
                "     处理：用编辑器另存为 UTF-8，或参照 backend/.env.example 重建"
            )


def check_dirs(fix: bool) -> None:
    for d in REQUIRED_DIRS:
        rel = d.relative_to(ROOT).as_posix()
        if d.is_file():
            problems.append(f"{rel} 是文件，应该是目录")
            continue
        if d.exists():
            continue
        if fix:
            d.mkdir(parents=True, exist_ok=True)
            notes.append(f"已创建目录 {rel}")
        else:
            problems.append(f"{rel} 不存在（Docker 会静默建成空目录，掩盖真实问题），加 --fix 可自动创建")


def check_compose() -> None:
    compose = ROOT / "docker-compose.yml"
    if not compose.exists():
        problems.append("找不到 docker-compose.yml，请确认在工程根目录下运行")
        return
    text = compose.read_text(encoding="utf-8", errors="replace")
    if "container_name:" in text:
        notes.append("docker-compose.yml 仍设置了 container_name，会阻碍 --scale 与多套环境并存")


def main() -> int:
    parser = argparse.ArgumentParser(description="knowledge-base-platform 启动前体检")
    parser.add_argument("--fix", action="store_true", help="自动修复可安全修复的问题")
    args = parser.parse_args()

    print(f"工程根目录: {ROOT}\n")
    check_env(args.fix)
    check_dirs(args.fix)
    check_compose()

    for n in notes:
        print(f"  · {n}")
    if problems:
        print()
        for p in problems:
            print(f"  ✗ {p}")
        print(f"\n体检未通过：{len(problems)} 项需要处理")
        return 1

    print("  ✓ 体检通过，可以执行: docker compose up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
