"""Гигиена дизайн-токенов (reskin-ветка): новый код — через токены.

Два инварианта:
1. Ссылки COLORS[/SEMANTIC[/UI_TOKENS[ живут только в f-строках,
   ключи существуют (иначе молчаливая каша или KeyError на экране).
2. Сырых hex за пределами styles.py не становится БОЛЬШЕ, чем на момент
   введения теста (196): старый дрейф вычищаем постепенно, новому — нет.
   Палитры ui_compat и графиков — осознанные исключения? Нет: они тоже
   считаются, поэтому их вынос — будущие коммиты hygiene-баatches.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Остаток (27) — осознанные палитры: ui_compat/QSS-палитры тем и _chart_palette
# в reports_screen. Их не трогаем (это и есть токены другого уровня).
ALLOW_RAW_HEX = 27


def _load_keys():
    out = {}
    for name in ("COLORS", "SEMANTIC", "UI_TOKENS", "DIFF", "CHART_SERIES"):
        node = next(n for n in ast.walk(ast.parse(
            (ROOT / "styles.py").read_text(encoding="utf-8")))
            if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets))
        out[name] = set(ast.literal_eval(node.value))
    return out


def test_token_refs_valid():
    keys = _load_keys()
    assert keys["COLORS"] and keys["SEMANTIC"] and keys["UI_TOKENS"]
    assert keys["DIFF"] and keys["CHART_SERIES"]
    bad = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "styles.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for mod in ("COLORS", "SEMANTIC", "UI_TOKENS", "DIFF",
                            "CHART_SERIES"):
                    if "{" + mod + "[" in node.value:
                        bad.append(f"{path.name}: plain string with {mod}[")
            if isinstance(node, ast.Subscript):
                func = node.value
                if isinstance(func, ast.Name) and func.id in keys:
                    sl = node.slice
                    key = sl.value if isinstance(sl, ast.Constant) else None
                    if isinstance(key, str) and key not in keys[func.id]:
                        bad.append(f"{path.name}: {func.id}[{key!r}] unknown")
    assert bad == [], bad


def test_raw_hex_not_growing():
    import re
    pat = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
    n = 0
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "styles.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            n += len(pat.findall(line))
    assert n <= ALLOW_RAW_HEX, f"raw hex {n} > {ALLOW_RAW_HEX}: новые цвета — в токены"
