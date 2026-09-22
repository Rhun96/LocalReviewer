"""Проверка секретов в репозитории (ТЗ V2.2 §7): только stdlib.

Запуск: python tools/check_secrets.py [root]
Выход 1 + список находок, если есть подозрения вне allowlist.

Что ловим: .env-файлы с непустыми значениями, приватные ключи,
api-ключи/токены известных форматов, password/secret с присвоением.
Allowlist тестовых фикстур: example.com, номера 900, слова
test/fake/dummy/placeholder/xxx — чтобы свои же тесты не краснели.
"""
import re
import sys
from pathlib import Path

SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"gho_[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[bpas]-[A-Za-z0-9-]{6,}"),
    re.compile(r"(?i)\bpassword\s*[:=]\s*['\"][^'\"]{4,}['\"]"),
    re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]

ALLOW_RES = [
    re.compile(r"example\.com"),
    re.compile(r"\+7 900"),
    re.compile(r"abcdef"),
    re.compile(r"1234567890?"),
    re.compile(r"(?i)\b(test|fake|dummy|placeholder|xxx+|12345)\b"),
]

SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "dist",
             "build", ".pytest_cache", ".ruff_cache", "backups", "logs"}
SKIP_SUFFIX = {".zip", ".sqlite", ".sqlite-journal", ".xlsx", ".pyc",
               ".png", ".jpg", ".ico", ".exe", ".docx", ".pptx"}


def _allowed(line: str) -> bool:
    return any(r.search(line) for r in ALLOW_RES)


def check_file(path: Path) -> list:
    hits = []
    if path.name == ".env":
        try:
            for i, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    _, _, val = s.partition("=")
                    if val.strip().strip("'\""):
                        hits.append(f"{path}:{i}: .env with value for {s.split('=')[0].strip()}")
        except OSError:
            pass
        return hits
    if path.suffix.lower() in SKIP_SUFFIX:
        return hits
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        if _allowed(line):
            continue
        for r in SECRET_RES:
            if r.search(line):
                hits.append(f"{path}:{i}: {line.strip()[:120]}")
                break
    return hits


def main(root: str = ".") -> int:
    base = Path(root)
    hits: list = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(d in p.parts for d in SKIP_DIRS):
            continue
        if p.name == ".env":
            hits.extend(check_file(p))
        elif p.suffix.lower() in (".py", ".md", ".txt", ".yml", ".yaml",
                                  ".toml", ".cfg", ".ini", ".json"):
            hits.extend(check_file(p))
    for h in hits:
        print(h)
    if hits:
        print(f"SECRETS CHECK FAILED: {len(hits)} findings")
        return 1
    print("secrets check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
