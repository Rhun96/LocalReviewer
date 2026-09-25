"""Гигиена дизайн-токенов (reskin-ветка): новый код — через токены.

Два инварианта:
1. Ссылки COLORS[/SEMANTIC[/UI_TOKENS[ живут только в f-строках,
   ключи существуют (иначе молчаливая каша или KeyError на экране).
2. Сырых hex за пределами styles.py нет (было 196, batch 4 занулил):
   палитры ui_compat и графиков тоже живут в styles.py токенами.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Остаток (0, reskin batch 4): палитры ui_compat/QSS-тем и _chart_palette
# в reports_screen переехали в styles.py (FLUENT_DARK/LIGHT, CHART_DARK/LIGHT).
# Сырых hex вне styles.py быть не должно.
ALLOW_RAW_HEX = 0


def _load_keys():
    out = {}
    for name in ("COLORS", "SEMANTIC", "UI_TOKENS", "DIFF", "CHART_SERIES",
                 "FLUENT_DARK", "FLUENT_LIGHT", "CHART_DARK", "CHART_LIGHT"):
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
    assert keys["FLUENT_DARK"] and keys["FLUENT_LIGHT"]
    assert keys["CHART_DARK"] and keys["CHART_LIGHT"]
    bad = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "styles.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for mod in ("COLORS", "SEMANTIC", "UI_TOKENS", "DIFF",
                            "CHART_SERIES", "FLUENT_DARK", "FLUENT_LIGHT",
                            "CHART_DARK", "CHART_LIGHT"):
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
