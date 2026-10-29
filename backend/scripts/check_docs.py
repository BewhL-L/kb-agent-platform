#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_docs.py — 文档与代码一致性校验器

来源：与 `project-processization` Skill 的 `scripts/check_docs.py` 保持同一套逻辑，
      仅追加「项目本地配置」一段（废弃表述、私有文件、路由来源），便于上游更新后逐段比对。

作用：生成学习指南时的事实核查只解决"写的时候对不对"；本脚本解决"写完以后还对不对"。
把四类可机械校验的一致性变成断言，接入 CI 后文档漂移会直接变红。

检查项：
  1. 数量一致：README 声明的"N passed""N 个测试" == tests 目录实际测试函数数
     （skip 的用例会被收集但不计入 passed，两个数字分开校验）
  2. 路径一致：反引号里以 backend/ frontend/ docker/ .github/ scripts/ 开头的路径必须真实存在
     （`scripts/x.py` 会兼容 `backend/scripts/x.py`）
  3. 表述一致：禁止出现已废弃的路径/数字/字段名（默认列表 + --forbid 追加）
  4. 私有文件：私有文档、.env 等绝不能出现在 git 跟踪列表里（--skip-git 可关）
  5. 接口一致（可选）：README 里的 `/api/...` 必须能在 --openapi / --routes 或 app 路由表中找到

用法：
  cd backend && python scripts/check_docs.py          # 最常用：默认按本文件位置推断项目根
  python scripts/check_docs.py --root . --json
  python scripts/check_docs.py --openapi openapi.json
  python scripts/check_docs.py --forbid "旧路径/" --skip-git
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════
# 项目本地配置（与上游 Skill 版本的唯一差异，上游更新时只需保持这段不动）
# ══════════════════════════════════════════════════════════════════════════

# 导入 app 之前固定环境：否则本地 .env 指向 postgres/qdrant，
# 读路由表会在 create_engine 阶段炸掉（脚本只读路由，不需要真连库）。
for _key, _value in (
    ("LLM_API_KEY", "docs-check-dummy"),
    ("DATABASE_URL", "sqlite:///./_docs_check.db"),
    ("VECTOR_PROVIDER", "chroma"),
    ("ASYNC_MODE", "thread"),
    ("RATE_LIMIT_ENABLED", "false"),
):
    os.environ.setdefault(_key, _value)

# 默认项目根：本文件位于 <root>/backend/scripts/check_docs.py
# 被复制到别处调试时 parents[2] 可能越界，退回当前目录，避免导入即崩
try:
    DEFAULT_ROOT = Path(__file__).resolve().parents[2]
except IndexError:
    DEFAULT_ROOT = Path.cwd()

# 废弃表述：值说明原因，报错时直接告诉人该改什么
PROJECT_FORBIDDEN = {
    "产品/": "仓库已拆分，旧目录不存在",
    "knowledge-base/产品": "部署路径已变更",
    "79 个": "测试数量已过期",
    "87 个": "测试数量已过期",
    "98 个": "测试数量已过期",
    "hit_at_k": "评测字段实际是 hit@k",
    "architecture.svg": "架构图已更新为 architecture-v3.svg",
}

# 私有文件：只检查"是否被 git 跟踪"，本地存在但被忽略的不算问题
PROJECT_PRIVATE = {
    "项目学习指导书.md": "私有指导书（含 AI 协作说明），只允许放在 项目前期构建/",
    "backend/.env": "含真实密钥，只允许用 .env.example",
    ".env": "含真实密钥，只允许用 .env.example",
}

# ══════════════════════════════════════════════════════════════════════════
# 以下逻辑与上游保持一致
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_FORBIDDEN = {"产品/": "旧目录名，仓库已拆分", "hit_at_k": "字段名应为 hit@k"}
DEFAULT_PRIVATE = {
    "项目学习指导书.md": "含 AI 协作说明的私有文档，不能进公开仓库",
    "backend/.env": "含真实密钥，只允许提交 .env.example",
    ".env": "含真实密钥，只允许提交 .env.example",
}

ROOTED_PREFIXES = ("backend/", "frontend/", "docker/", ".github/", "scripts/")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
BACKTICK = re.compile(r"`([^`\n]+)`")
BRACES = re.compile(r"\{[^}]+\}")


def _endpoint_of(token: str) -> str:
    """把文档里的写法归一成纯路径。

    `POST /api/chat`      -> `/api/chat`（README 里绝大多数是这个写法）
    `/api/chat?top_k=5`   -> `/api/chat`
    """
    text = token.strip()
    head, _, rest = text.partition(" ")
    if rest and head.upper() in METHODS:
        text = rest.strip()
    return text.split("?")[0].strip()


def _is_skip_decorator(node: ast.AST) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "skip"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
    )


def count_tests(tests_dir: Path) -> tuple:
    """返回 (测试函数总数, 被 skip 的数量)"""
    total = skipped = 0
    for path in sorted(tests_dir.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        module_skipped = any(
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "pytestmark" for t in node.targets)
            and any(_is_skip_decorator(n) for n in ast.walk(node.value))
            for node in tree.body
        )
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                total += 1
                if module_skipped or any(_is_skip_decorator(d) for d in node.decorator_list):
                    skipped += 1
    return total, skipped


def check_numbers(text: str, tests_dir: Path) -> list:
    errors = []
    total, skipped = count_tests(tests_dir)
    if total == 0:
        return [f"未在 {tests_dir} 找到测试（用 --tests 指定目录）"]

    passed = total - skipped
    # 只认"后端"的声明：排除前端那行 `npm run test  # 5 passed`
    claimed = set()
    for line in text.splitlines():
        low = line.lower()
        if "passed" in low and not any(k in low for k in ("npm", "vitest", "frontend")):
            claimed.update(re.findall(r"(\d+)\s*passed", line))
    claimed.update(re.findall(r"(\d+)\s*个测试", text))

    if not claimed:
        errors.append("文档未声明测试数量（建议写 `pytest -q  # N passed`），无法校验")
    for number in sorted(claimed):
        if int(number) not in (passed, total):
            errors.append(
                f"测试数量不一致：文档写 {number}，实际 {passed} passed / {total} 个测试函数"
            )
    return errors


def check_paths(text: str, root: Path) -> list:
    errors, seen = [], set()
    for token in BACKTICK.findall(text):
        token = token.strip().rstrip("/")
        if not token.startswith(ROOTED_PREFIXES) or token in seen:
            continue
        if any(ch in token for ch in "{}* ") or "<" in token:
            continue
        seen.add(token)
        # 文档里常把 backend/scripts/xx.py 简写成 scripts/xx.py，这里做一次兼容
        candidates = [root / token, root / "backend" / token]
        if not any(c.exists() for c in candidates):
            errors.append(f"路径不存在：`{token}`")
    return errors


def check_forbidden(text: str, forbidden: dict) -> list:
    return [
        f"出现已废弃表述 `{needle}`：{reason}"
        for needle, reason in forbidden.items()
        if needle in text
    ]


def check_private(root: Path, private: dict) -> list:
    try:
        result = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"跳过私有文件检查：{type(exc).__name__}"]
    if result.returncode != 0:
        return ["跳过私有文件检查：不在 git 仓库中"]
    tracked = set(result.stdout.splitlines())
    return [
        f"版本库里出现 `{name}`：{reason}"
        for name, reason in private.items()
        if name in tracked
    ]


def _stub_chromadb_if_missing() -> None:
    """本地 venv 常常没装 chromadb（测试里是替身）。导入阶段只需要 PersistentClient 这个符号。"""
    import types

    try:
        import chromadb  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    stub = types.ModuleType("chromadb")

    class _StubClient:
        def __init__(self, *args, **kwargs):
            self.collections = {}

        def get_or_create_collection(self, name, **kwargs):
            raise RuntimeError("check_docs 只读取路由表，不应真正访问向量库")

    stub.PersistentClient = _StubClient
    sys.modules["chromadb"] = stub


def load_routes_from_app(backend_dir: Path) -> set:
    """本项目的默认路由来源：直接读 FastAPI 的 OpenAPI schema，免去先导出文件。

    导入失败（依赖没装全）时返回空集合，由调用方降级为"跳过"而不是判失败。
    """
    _stub_chromadb_if_missing()
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    try:
        from app.main import app  # 延迟导入
    except Exception as exc:  # noqa: BLE001
        # 依赖不全时降级为"跳过"而不是判失败；提示走 stderr，避免污染 --json 输出
        print(f"[接口路径] 跳过：无法导入 app（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return set()

    # 用 OpenAPI schema 而不是 app.routes：新版本 FastAPI 的 app.routes 里是
    # _IncludedRouter 占位对象，不会展开子路由；schema 是跨版本稳定的真路径来源。
    return {
        BRACES.sub("{}", path).rstrip("/")
        for path in app.openapi().get("paths", {})
        if path.startswith(("/api", "/a2a", "/embed"))
    }


def load_routes(openapi: Path = None, routes_file: Path = None) -> set:
    paths = set()
    if openapi and openapi.exists():
        data = json.loads(openapi.read_text(encoding="utf-8"))
        paths.update(data.get("paths", {}).keys())
    if routes_file and routes_file.exists():
        paths.update(
            line.strip()
            for line in routes_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return {BRACES.sub("{}", p).rstrip("/") for p in paths}


def check_endpoints(text: str, routes: set) -> list:
    if not routes:
        return []
    errors, seen = [], set()
    for token in BACKTICK.findall(text):
        endpoint = _endpoint_of(token)
        if not endpoint.startswith(("/api/", "/a2a/", "/embed/")):
            continue
        doc_path = BRACES.sub("{}", endpoint.rstrip("/"))
        if doc_path in seen:
            continue
        seen.add(doc_path)
        if not any(r == doc_path or r.startswith(doc_path + "/") for r in routes):
            errors.append(f"接口不存在：`{token}`（路由表中无匹配项）")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="文档与代码一致性校验")
    parser.add_argument("--root", default="", help="项目根目录（默认按脚本位置推断）")
    parser.add_argument("--doc", default="README.md", help="待校验文档（相对 root）")
    parser.add_argument("--tests", default="backend/tests", help="测试目录（相对 root）")
    parser.add_argument("--openapi", default="", help="openapi.json 路径（可选）")
    parser.add_argument("--routes", default="", help="每行一个路由路径的文本文件（可选）")
    parser.add_argument("--forbid", action="append", default=[], help="追加禁止表述，可多次")
    parser.add_argument("--private", action="append", default=[], help="追加私有文件，可多次")
    parser.add_argument("--skip-git", action="store_true", help="跳过 git 私有文件检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else DEFAULT_ROOT
    doc = root / args.doc
    if not doc.exists():
        print(f"找不到文档：{doc}")
        return 1

    text = doc.read_text(encoding="utf-8")
    forbidden = dict(DEFAULT_FORBIDDEN)
    forbidden.update(PROJECT_FORBIDDEN)
    forbidden.update({item: "由 --forbid 指定" for item in args.forbid})
    private = dict(DEFAULT_PRIVATE)
    private.update(PROJECT_PRIVATE)
    private.update({item: "由 --private 指定" for item in args.private})

    if args.openapi or args.routes:
        routes = load_routes(
            Path(args.openapi) if args.openapi else None,
            Path(args.routes) if args.routes else None,
        )
    else:
        routes = load_routes_from_app(root / "backend")

    checks = [
        ("测试数量", lambda: check_numbers(text, root / args.tests)),
        ("文档路径", lambda: check_paths(text, root)),
        ("废弃表述", lambda: check_forbidden(text, forbidden)),
    ]
    if not args.skip_git:
        checks.append(("私有文件", lambda: check_private(root, private)))
    if routes:
        checks.append(("接口路径", lambda: check_endpoints(text, routes)))
    elif args.openapi or args.routes:
        print("[接口路径] 跳过：--openapi / --routes 没有解析出任何路径", file=sys.stderr)

    results, all_errors = [], []
    for name, func in checks:
        errors = func()
        results.append({"name": name, "ok": not errors, "errors": errors})
        all_errors.extend(errors)

    if args.json:
        print(json.dumps({"doc": str(doc), "results": results}, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"[{item['name']}] {'OK' if item['ok'] else str(len(item['errors'])) + ' 处不一致'}")
        if all_errors:
            print("\n发现文档与代码不一致：")
            for error in all_errors:
                print(f"  - {error}")
            print("\n修完再跑一次。")
        else:
            print("\n文档与代码一致。")
    return 0 if not all_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
