"""Der Container läuft auf Python 3.11 (Debian 12), lokal wird mit neuerem
Python entwickelt. Ab 3.12 erlaubt Python Dinge, an denen 3.11 schon beim
Import scheitert — die App startet dann gar nicht (so geschehen am
2026-10-01: ein über zwei Zeilen umbrochener f-String-Ausdruck).

Dieser Test findet solche Stellen per tokenize, bevor sie ins Deploy gehen:
- f-String über mehrere Zeilen (Ausdruck umbrochen)
- im f-String-Ausdruck ein String mit DEMSELBEN Anführungszeichen
- Backslash oder Kommentar im f-String-Ausdruck
- `type X = …`, Typparameter `def f[T]`, `except A, B:` ohne Klammern

Nur sinnvoll unter Python ≥ 3.12 (dort haben f-Strings eigene Tokens);
unter 3.11 selbst würde schon der Import der App scheitern.
"""
from __future__ import annotations

import ast
import sys
import tokenize
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12),
                                reason="f-String-Tokens gibt es erst ab 3.12")


def _funde(p: Path) -> list[str]:
    quelle = p.read_text(encoding="utf-8")
    out = []
    baum = ast.parse(quelle)
    for k in ast.walk(baum):
        if k.__class__.__name__ == "TypeAlias":
            out.append(f"{p}:{k.lineno}: type-Alias")
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and getattr(k, "type_params", None):
            out.append(f"{p}:{k.lineno}: Typparameter")
    for i, z in enumerate(quelle.splitlines(), 1):
        s = z.strip()
        if s.startswith("except ") and "," in s.split(":")[0] \
                and "(" not in s.split(":")[0] and " as " not in s:
            out.append(f"{p}:{i}: except ohne Klammern")

    offen: list[tuple[str, int]] = []
    tiefe: list[int] = []
    for t in tokenize.generate_tokens(iter(quelle.splitlines(keepends=True)).__next__):
        name = tokenize.tok_name[t.type]
        if name == "FSTRING_START":
            offen.append((t.string.lstrip("rRfFbBuU"), t.start[0]))
            tiefe.append(0)
            continue
        if name == "FSTRING_END":
            q, start = offen.pop()
            tiefe.pop()
            if t.end[0] != start and len(q) == 1:
                out.append(f"{p}:{start}: f-String über mehrere Zeilen")
            continue
        if not offen:
            continue
        if name == "OP" and t.string == "{":
            tiefe[-1] += 1
        elif name == "OP" and t.string == "}":
            tiefe[-1] -= 1
        if tiefe[-1] <= 0:
            continue
        aussen = offen[-1][0] if name == "STRING" else (offen[-2][0] if len(offen) > 1 else "")
        if name in ("STRING", "FSTRING_START") and len(aussen) == 1 \
                and t.string.lstrip("rRfFbBuU").startswith(aussen):
            out.append(f"{p}:{t.start[0]}: gleiches Anführungszeichen im f-String-Ausdruck")
        if name == "COMMENT":
            out.append(f"{p}:{t.start[0]}: Kommentar im f-String-Ausdruck")
        if name == "STRING" and "\\" in t.string:
            out.append(f"{p}:{t.start[0]}: Backslash im f-String-Ausdruck")
    return out


def test_kein_python_312_syntax_im_code():
    funde = []
    for ordner in ("app", "tests"):
        for p in sorted((WURZEL / ordner).rglob("*.py")):
            if "__pycache__" not in p.parts:
                funde += _funde(p)
    assert not funde, "Syntax erst ab Python 3.12 (Container hat 3.11):\n" + "\n".join(funde)


def test_pruefer_erkennt_umbrochenen_f_string(tmp_path):
    """Gegenprobe mit genau dem Fehler vom 2026-10-01."""
    p = tmp_path / "x.py"
    p.write_text('a = 1\nb = f"{max(a,\n        2)}"\n', encoding="utf-8")
    assert any("mehrere Zeilen" in f for f in _funde(p))
