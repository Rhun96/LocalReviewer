"""V2.2 §2-§4, §6: логи без контента, clipboard-fingerprint, скан, обезличивание."""
import tempfile

import anonymizer_service as anon
import clipboard_service as clip
import privacy_scan_service as scan


def test_logs_have_no_case_content():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = []
    for p in root.glob("*.py"):
        if p.name.startswith("test_"):
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(t.splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
                continue
            if "logger." not in s and "logging." not in s:
                continue
            ll = s.lower()
            if any(k in ll for k in (
                    "primary_text", "response_text", "operator_response",
                    "review_comment", "actual_behavior", "expected_behavior")):
                bad.append(f"{p.name}:{i}: {s[:120]}")
    assert bad == [], bad


def test_content_debug_off_by_default(monkeypatch):
    monkeypatch.delenv("LOCALREVIEWER_DEBUG_CONTENT", raising=False)
    try:
        from PySide6.QtCore import QSettings
        QSettings("LocalReviewer", "LocalReviewer").remove("privacy/debug_content")
    except Exception:
        pass
    import app_logging as _log
    assert _log.is_content_debug_enabled() is False
    monkeypatch.setenv("LOCALREVIEWER_DEBUG_CONTENT", "1")
    assert _log.is_content_debug_enabled() is True


def test_offline_no_network_calls():
    """V2.2 §31: основной workflow без сети — в коде нет сетевых импортов."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    banned = {"requests", "urllib", "http", "socket", "httpx", "aiohttp"}
    bad = []
    for p in root.glob("*.py"):
        if p.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if (a.name or "").split(".")[0] in banned:
                        bad.append(f"{p.name}: import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] in banned:
                    bad.append(f"{p.name}: from {node.module} import ...")
    assert bad == [], bad


def test_secrets_checker_clean_on_repo():
    import subprocess
    import sys
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "tools/check_secrets.py", str(root)],
                       capture_output=True, text=True, cwd=str(root))
    assert r.returncode == 0, r.stdout + r.stderr


def _pump_clipboard():
    """Настоящий виндовый буфер шлёт dataChanged асинхронно (не offscreen)."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    QApplication.instance().processEvents()
    QTest.qWait(150)
    QApplication.instance().processEvents()


def test_clipboard_monitor_arms_only_inapp_copies(monkeypatch):
    """Монитор: нативная копия из программы взводит, чужая — игнор."""
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QGuiApplication
    QApplication.instance() or QApplication([])
    import clipboard_service as _clip
    assert _clip.install_monitor() is True
    saved_cb = QGuiApplication.clipboard().text()
    w = QWidget()
    try:
        _clip.reset_pending()
        # чужое (активного окна нет) — не трогаем
        monkeypatch.setattr(QApplication, "activeWindow",
                            classmethod(lambda _cls: None))
        QGuiApplication.clipboard().setText("из jira")
        _pump_clipboard()
        assert _clip.pending_hash() is None
        assert _clip.countdown_state() is None
        # своё (окно активно) — взводим
        monkeypatch.setattr(QApplication, "activeWindow",
                            classmethod(lambda _cls: w))
        QGuiApplication.clipboard().setText("выделение из кейса")
        _pump_clipboard()
        assert _clip.pending_hash() == _clip.fingerprint("выделение из кейса")
        assert isinstance(_clip.countdown_state(), int)
        # пусто — игнор
        QGuiApplication.clipboard().clear()
        _pump_clipboard()
        assert _clip.countdown_state() is None
    finally:
        w.close()
        _clip.reset_pending()
        QGuiApplication.clipboard().setText(saved_cb)


def test_clipboard_monitor_respects_off(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QGuiApplication
    QApplication.instance() or QApplication([])
    import clipboard_service as _clip
    prev = _clip.get_clear_after()
    saved_cb = QGuiApplication.clipboard().text()
    w = QWidget()
    try:
        _clip.set_clear_after(0)
        _clip.reset_pending()
        monkeypatch.setattr(QApplication, "activeWindow",
                            classmethod(lambda _cls: w))
        QGuiApplication.clipboard().setText("что-то")
        _pump_clipboard()
        assert _clip.pending_hash() is None
    finally:
        _clip.set_clear_after(prev)
        w.close()
        _clip.reset_pending()
        QGuiApplication.clipboard().setText(saved_cb)


def test_clipboard_countdown_state(monkeypatch):
    """Состояние для пилюли: секунды после копии, None — если выкл/пусто/чужое."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QGuiApplication
    QApplication.instance() or QApplication([])
    clip.reset_pending()
    assert clip.countdown_state() is None
    clip.safe_copy("секрет")
    left = clip.countdown_state()
    assert isinstance(left, int) and left >= 1, left
    # чужое поверх (окно неактивно) — пилюлю прячем
    monkeypatch.setattr(QApplication, "activeWindow",
                        classmethod(lambda _cls: None))
    QGuiApplication.clipboard().setText("пользовательское")
    assert clip.countdown_state() is None
    clip.reset_pending()


def test_clipboard_fingerprint_only_own():
    clip.reset_pending()
    assert clip.should_clear(None, "что-то") is False
    assert clip.should_clear("abc", "") is False
    assert clip.should_clear("abc", None) is False
    h = clip.fingerprint("секретный баг-репорт")
    assert clip.should_clear(h, "секретный баг-репорт") is True
    assert clip.should_clear(h, "пользователь скопировал поверх") is False
    assert clip.get_clear_after() in (0, 30, 60, 300)


def test_privacy_scan_counts_unicode():
    s = scan.scan_text("Позвони +7 900 123-45-67 или ivan@example.com, вот https://intra.local/x")
    assert s["phones"] >= 1
    assert s["emails"] == 1
    assert s["urls"] == 1
    assert scan.scan_text("") == {"emails": 0, "phones": 0, "urls": 0, "secrets": 0}
    assert scan.scan_text(None)["emails"] == 0
    tok = scan.scan_text("вот token: ghp_abcdef1234567890 и sk-abcdef1234567890")
    assert tok["secrets"] >= 1
    # номер обращения — не секрет и не телефон
    assert scan.scan_text("Обращение № 12345678")["secrets"] == 0


def test_privacy_scan_export_counts():
    from database import init_database
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "позвони +7 900 111-22-33"},
                 {"q": "обычный вопрос без контактов"}])
    out = scan.scan_export(p)
    assert out["cases"] == 2
    assert out["phones"] >= 1
    assert out["has_sensitive"] is True


def test_anonymizer_stable_and_copy_only():
    a = anon.Anonymizer()
    src = "Иван, +7 900 123-45-67, ivan@example.com, см. https://ex.com/a"
    once = a.anonymize(src)
    twice = a.anonymize("снова +7 900 123-45-67 и ivan@example.com")
    assert "<PHONE_1>" in once and "<EMAIL_1>" in once and "<URL_1>" in once
    # стабильность: тот же объект — тот же плейсхолдер
    assert "<PHONE_1>" in twice and "<EMAIL_1>" in twice
    # исходник не тронут (строки иммутабельны, проверяем явно)
    assert "+7 900 123-45-67" in src and "ivan@example.com" in src
    # разные объекты — разные номера
    other = a.anonymize("другой +7 900 999-88-77")
    assert "<PHONE_2>" in other
    # PERSON не трогаем
    assert "Иван" in once
    st = a.stats()
    assert st["PHONE"] == 2 and st["EMAIL"] == 1
