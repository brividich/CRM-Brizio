"""Genera il blocco gemello `body.theme-dark` per i <style> di pagina che hardcodano colori chiari.

Uso: python tools/gen_dark_block.py [--apply] <template.html|file.css> ...
Senza --apply stampa il blocco; con --apply lo aggiunge in coda all'ultimo <style> (o al CSS).
Le mappe colore sono le stesse di tools/gen_dark_safety.py (stili inline).
"""
from __future__ import annotations
import re, sys, os

sys.path.insert(0, os.path.dirname(__file__))
from gen_dark_safety import TEXT, BG, BORDER  # noqa: E402

MARK = "/* ── Tema scuro: gemello generato da tools/gen_dark_block.py (non modificare a mano) ── */"


def _lookup(table: dict, value: str) -> str | None:
    m = re.search(r"#([0-9a-fA-F]{3,6})\b", value)
    if not m:
        return None
    h = m.group(1).lower()
    if len(h) == 3:
        h6 = "".join(c * 2 for c in h)
    else:
        h6 = h
    for tok, hexes in table.items():
        for x in hexes:
            x6 = "".join(c * 2 for c in x) if len(x) == 3 else x
            if x6 == h6:
                return tok
    return None


def _lum(h: str) -> float:
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


TOKEN_TEXT = re.compile(r"(ink|text|navy|title|fg|muted|label|heading)", re.I)
TOKEN_BG = re.compile(r"(bg|card|surface|panel|surfalt|paper)", re.I)
TOKEN_BORDER = re.compile(r"(line|border|rule|divider)", re.I)


# token del tema base (theme.css): mai ribaltarli da qui, li definisce gia' body.theme-dark in theme.css
CORE_TOKENS = {"--bg", "--surface", "--border", "--text", "--text-mid", "--text-light", "--primary", "--primary-mid",
               "--accent", "--accent-light", "--success", "--success-bg", "--warning", "--warning-bg", "--danger",
               "--danger-bg", "--surface-alt", "--hover-bg", "--thead-bg", "--tbody-hover", "--card-head-bg", "--vh"}


def _token_dark(name: str, val: str) -> str | None:
    """Valore scuro per una custom property del sotto-tema, in base al nome e alla luminosita'."""
    if name in CORE_TOKENS:
        return None
    m = re.search(r"#([0-9a-fA-F]{3,6})(?![0-9a-fA-F])", val)
    if not m:
        return None
    lum = _lum(m.group(1).lower())
    out = None
    if TOKEN_BORDER.search(name):
        out = _lookup(BORDER, val) or ("var(--border)" if lum > 0.75 else None)
    elif TOKEN_BG.search(name):
        out = _lookup(BG, val) or ("var(--surface)" if lum > 0.9 else "var(--surface-alt,#0f1b2d)" if lum > 0.75 else None)
    elif TOKEN_TEXT.search(name):
        out = _lookup(TEXT, val) or ("var(--text)" if lum < 0.15 else "var(--text-mid)" if lum < 0.35 else None)
    if out and f"var({name})" in out:
        return None  # --x:var(--x) sarebbe un ciclo: la proprieta' diventerebbe invalida
    return out


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def top_level_rules(css: str):
    """Restituisce (selettore, dichiarazioni) delle regole di primo livello, saltando gli @-blocchi."""
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            return
        head = css[i:j].strip()
        # chiusura bilanciata
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        i = k
        if not head or head.startswith("@"):
            continue
        if "{" in body:  # nesting: ignora
            continue
        yield head, body


def dark_decls(body: str) -> list[str]:
    out = []
    for decl in body.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if "!important" in val:
            continue
        if prop.startswith("--"):
            # token di sotto-tema (--fmd-navy, --hub-ink...): ribaltato solo se il nome dice a cosa serve
            tok = _token_dark(prop, val)
            if tok:
                out.append(f"{prop}:{tok}")
            continue
        if "var(" in val:
            # --primary/--primary-mid sono il blu del marchio: come testo, in scuro, restano navy illeggibile
            if prop == "color" and re.match(r"var\(--primary(-mid)?[,)]", val):
                out.append("color:#93c5fd")
            continue
        if prop == "color":
            tok = _lookup(TEXT, val)
            if tok:
                out.append(f"color:{tok}")
        elif prop in ("background", "background-color"):
            if "url(" in val:
                continue
            if "gradient(" in val:
                # sfumatura fra soli colori chiari (#fbfdff -> #f8fbff): in scuro diventa superficie piatta
                hexes = re.findall(r"#([0-9a-fA-F]{3,6})(?![0-9a-fA-F])", val)
                if hexes and all(_lum(h) > 0.85 for h in hexes):
                    out.append("background:var(--surface-alt,#0f1b2d)")
                continue
            tok = _lookup(BG, val)
            if tok:
                out.append(f"background:{tok}")
        elif prop in ("border", "border-color", "border-top", "border-bottom", "border-left", "border-right"):
            tok = _lookup(BORDER, val)
            if tok:
                out.append(f"border-color:{tok}")
    return out


def build_block(css: str, src: str = "") -> str:
    rules = []
    for sel, body in top_level_rules(strip_comments(css)):
        if "theme-dark" in sel:
            continue
        first = sel.split(",")[0].strip()
        if src and re.search(r"theme-dark\s+" + re.escape(first) + r"\s*[,{:\s]", src):
            continue  # gia' coperto da un gemello scritto a mano
        decls = dark_decls(body)
        if not decls:
            continue
        sels = ",".join(("body.theme-dark" if s.strip() in (":root", "html", "body") else "body.theme-dark " + s.strip()) for s in sel.split(",") if s.strip())
        rules.append(f"{sels}{{{';'.join(dict.fromkeys(decls))}}}")
    return "\n".join(rules)


STYLE_RE = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.S | re.I)


def process(path: str, apply: bool) -> int:
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        # blocco gia' generato: lo tolgo e lo rigenero (il blocco finisce a </style> o a fine file)
        a = src.index(MARK)
        b = src.find("</style>", a)
        src = src[:a].rstrip() + ("\n" if b < 0 else "\n  " + src[b:])
        css_only = src if path.endswith(".css") else "\n".join(m.group(2) for m in STYLE_RE.finditer(src))
        if build_block(css_only, src) == "":
            if apply:
                open(path, "w", encoding="utf-8", newline="").write(src)
            return 0
    if path.endswith(".css"):
        block = build_block(src, src)
        if not block:
            return 0
        new = src.rstrip() + "\n\n" + MARK + "\n" + block + "\n"
    else:
        blocks = list(STYLE_RE.finditer(src))
        if not blocks:
            return 0
        block = build_block("\n".join(m.group(2) for m in blocks), src)
        if not block:
            return 0
        last = blocks[-1]
        new = src[:last.start(3)] + "\n" + MARK + "\n" + block + "\n" + src[last.start(3):]
    n = block.count("\n") + 1
    if apply:
        open(path, "w", encoding="utf-8", newline="").write(new)
        print(f"++ {path}: {n} regole aggiunte")
    else:
        print(f"== {path}: {n} regole\n{block}\n")
    return n


if __name__ == "__main__":
    args = sys.argv[1:]
    apply = "--apply" in args
    tot = 0
    for p in [a for a in args if a != "--apply"]:
        tot += process(p, apply)
    print("totale regole:", tot)
