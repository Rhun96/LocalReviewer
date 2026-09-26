"""Пинит classic-палитру для детерминированного сьюта.

Выбор варианта в styles.py: env LR_PALETTE > QSettings ui/palette.
Без этого тесты с hex-ассёртами на машине с включённым ref плыли бы.
"""
import os

os.environ.setdefault("LR_PALETTE", "classic")
