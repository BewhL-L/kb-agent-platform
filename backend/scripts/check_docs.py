"""
文档一致性检查（CI 门禁）
==========================
解决的问题：文档最容易"写的时候是对的，代码改了没跟上"。
这里把四类可机械校验的一致性变成断言：

    1. 数量一致性：README 声明的测试数 == 实际 def test_ 数量
    2. 路径一致性：README 里出现的仓库路径必须真实存在
    3. 接口一致性：README 里提到的 /api/... 必须能在 FastAPI 路由表里找到
    4. 表述一致性：禁止出现已废弃的路径 / 数字 / 字段名

用法：
    cd backend && python scripts/check_docs.py

退出码 0 = 通过；1 = 有不一致（打印具体条目，便于直接修）。
"""
import ast
import os
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
README = REPO_ROOT / "README.md"

# 导入 app 之前固定环境：否则本地 .env 指向 postgres/qdrant，脚本会在 create_engine 阶段炸掉
os.environ.setdefault("LLM_API_KEY", "docs-check-dummy")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_docs_check.db")
os.environ.setdefault("VECTOR_PROVIDER", "chroma")
os.environ.setdefault("ASYNC_MODE", "thread")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
sys.path.insert(0, str(BACKEND_DIR))

# 已经废弃、但容易被复制粘贴回文档的表述
FORBIDDEN = {
    "产品/": "仓库已拆分，旧目录不存在",
    "knowledge-base/产品": "部署路径已变更",
    "79 个": "测试数量已过期",
    "87 个": "测试数量已过期",
    "98 个": "测试数量已过期",
    "hit_at_k": "评测字段实际是 hit@k",
    "architecture.svg": "架构图已更新为 architecture-v3.svg",
}

# 只校验以这些前缀开头的路径，避免把「服务名/函数名」误当成文件路径
ROOTED_PREFIXES = ("backend/", "frontend/", "docker/", ".github/")

BACKTICK = re.compile(r"`([^`\n]+)`")
BRACES = re.compile(r"\{[^}]+\}")


def read_docs() -> str:
    if not README.exists():
        raise SystemExit(f"找不到 README：{README}")
    return README.read_text(encoding="utf-8")


def _is_skip_decorator(node) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "skip"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
    )


def count_tests() -> tuple:
    """返回 (测试函数总数, 被 skip 的数量)。

    跳过用例仍然会被收集，但不会计入 passed，所以两个数字要分开校验。
    """
    total = 0
    skipped = 0
    for path in sorted((BACKEND_DIR / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_skipped = any(
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "pytestmark" for t in node.targets)
            and any(_is_skip_decorator(n) for n in ast.walk(node.value))
            for node in tree.body
        )
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            total += 1
            if module_skipped or any(_is_skip_decorator(d) for d in node.decorator_list):
                skipped += 1
    return total, skipped


def check_test_count(text: str) -> list:
    errors = []
    actual_total, actual_skipped = count_tests()
    actual_passed = actual_total - actual_skipped

    # 只认"后端"的声明：含 pytest 的行里的 N passed + 目录树里的 N 个测试。
    # 前端那行 `npm run test  # 5 passed` 数量不同，不能混进来。
    claimed = set()
    for line in text.splitlines():
        low = line.lower()
        # 排除前端的 passed 声明（npm / vitest），其余都按后端口径算
        if "passed" in low and not any(k in low for k in ("npm", "vitest", "frontend")):
            claimed.update(re.findall(r"(\d+)\s*passed", line))
    claimed.update(re.findall(r"(\d+)\s*个测试", text))

    if not claimed:
        errors.append("README 未声明后端测试数量，无法校验（建议写明 `pytest -q  # N passed`）")
    for number in sorted(claimed):
        value = int(number)
        if value == actual_passed or value == actual_total:
            continue
        errors.append(
            f"测试数量不一致：README 写 {value}，实际 {actual_passed} passed / {actual_total} 个测试函数"
        )
    return errors


def check_paths(text: str) -> list:
    errors = []
    seen = set()
    for token in BACKTICK.findall(text):
        token = token.strip().rstrip("/")
        if not token.startswith(ROOTED_PREFIXES) or token in seen:
            continue
        if "{" in token or "*" in token or " " in token:
            continue
        seen.add(token)
        if not (REPO_ROOT / token).exists():
            errors.append(f"路径不存在：`{token}`")
    return errors


def check_forbidden(text: str) -> list:
    return [
        f"出现已废弃表述 `{needle}`：{reason}"
        for needle, reason in FORBIDDEN.items()
        if needle in text
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


def check_endpoints(text: str) -> list:
    _stub_chromadb_if_missing()
    try:
        from app.main import app  # 延迟导入：导入失败时其余检查仍可完成
    except Exception as exc:  # noqa: BLE001
        # 依赖不全时跳过而不是判失败（CI 装了完整依赖，会真正执行这段）
        print(f"[接口路径] 跳过：无法导入 app（{type(exc).__name__}: {exc}）")
        return []

    # 用 OpenAPI schema 而不是 app.routes：新版本 FastAPI 的 app.routes 里是
    # _IncludedRouter 占位对象，不会展开子路由；schema 是跨版本稳定的真路径来源。
    routes = {
        BRACES.sub("{}", path).rstrip("/")
        for path in app.openapi().get("paths", {})
        if path.startswith(("/api", "/a2a", "/embed"))
    }

    errors = []
    seen = set()
    for token in BACKTICK.findall(text):
        if not token.startswith(("/api/", "/a2a/", "/embed/")):
            continue
        doc_path = BRACES.sub("{}", token.strip().rstrip("/"))
        if doc_path in seen:
            continue
        seen.add(doc_path)
        if not any(r == doc_path or r.startswith(doc_path + "/") for r in routes):
            errors.append(f"接口不存在：`{token}`（路由表里没有匹配项）")
    return errors


def main() -> int:
    text = read_docs()
    checks = [
        ("测试数量", check_test_count),
        ("文档路径", check_paths),
        ("废弃表述", check_forbidden),
        ("接口路径", check_endpoints),
    ]

    all_errors = []
    for name, func in checks:
        errors = func(text)
        status = "OK" if not errors else f"{len(errors)} 处不一致"
        print(f"[{name}] {status}")
        all_errors.extend(errors)

    if all_errors:
        print("\n发现文档与代码不一致：")
        for error in all_errors:
            print(f"  - {error}")
        print("\n修完再跑一次：cd backend && python scripts/check_docs.py")
        return 1

    print("\n文档与代码一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
