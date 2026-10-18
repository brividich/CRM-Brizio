"""Genera django_app/core/static/core/css/dark-safety.css: rete di sicurezza del tema scuro
per i colori scritti INLINE (style="...") nei template.

Uso: python tools/gen_dark_safety.py django_app/core/static/core/css/dark-safety.css
Le stesse mappe sono usate da tools/gen_dark_block.py per i <style> di pagina.
"""
import sys

# testo scuro -> token del tema / tinta chiara
TEXT = {
    "var(--text)": ["0f172a", "0c2545", "1e293b", "182232", "1c2b42", "334155", "374151", "1a202c", "111827", "244973", "1e2333", "0f2338",
                    "0b1220", "1f2937", "263238", "2d3748", "000", "000000", "111", "222", "333", "1a1a1a"],
    "var(--text-mid)": ["475569", "4a5568", "4b5563", "5b6b82", "6b7280", "1e3a5f", "555", "666", "444"],
    "var(--text-light)": ["64748b", "7c8aa2", "92a0b5", "718096", "777", "888"],
    # semantici: scuri in chiaro -> chiari in scuro
    "#fca5a5": ["991b1b", "b91c1c", "c53030", "7f1d1d", "a94442", "dc2626", "b53d3d"],
    "#fdba74": ["9a3412", "c2410c", "ea580c", "7c2d12"],
    "#fcd34d": ["92400e", "b45309", "a86a14", "854d0e", "78350f", "a16207"],
    "#93c5fd": ["1d4ed8", "1e40af", "0369a1", "1665a3", "2563eb", "1e3a8a", "075985", "0c4a6e", "1f87cd", "002b5c", "2f5f89", "1f5fb3", "1f5c91"],
    "#86efac": ["166534", "15803d", "065f46", "0f766e", "16a34a", "14532d", "047857", "115e59"],
    "#c4b5fd": ["5b21b6", "6d28d9", "7e22ce", "4c1d95"],
}
# sfondi chiari -> superficie scura / tinta traslucida
BG = {
    "var(--surface)": ["fff", "ffffff", "fafafa"],
    "var(--surface-alt,#0f1b2d)": ["f8fafc", "f1f5f9", "f9fafb", "f3f4f6", "eef2f7", "eef3f8", "eef1f6", "e2e8f0", "f5f7fa", "f4f6f8", "f8fbff", "fbfdff", "f6f8fb", "f5f7fb", "f7f9fc", "f9fbfd", "f5f5f5", "f0f3f7"],
    "rgba(229,62,62,.16)": ["fee2e2", "fef2f2", "fff5f5", "fecaca", "fde2e2"],
    "rgba(214,158,46,.16)": ["fef3c7", "fffbeb", "fff7ed", "ffedd5", "fdf1de", "fff1e3", "fff5ec", "fef9c3", "fef08a", "fed7aa", "fef4d0", "f8f0e2"],
    "rgba(59,130,246,.18)": ["dbeafe", "eff6ff", "e0f2fe", "e4f1fb", "e0f7ff", "bfdbfe", "dfedfe", "ecfeff", "cffafe"],
    "rgba(56,161,105,.18)": ["dcfce7", "d1fae5", "f0fdf4", "f0fdfa", "ecfdf5", "bbf7d0", "daf8e5"],
    "rgba(139,92,246,.2)": ["ede9fe", "f5f3ff", "ddd6fe", "e0e7ff", "eef2ff"],
}
# variabili fittizie usate inline (non esistono in theme.css: resta sempre la riserva chiara)
FAKE_VARS = ["var(--bg-alt", "var(--bg-card", "var(--bg-hover", "var(--surface-2"]
# bordi chiari -> bordo del tema
BORDER = {"var(--border)": ["e2e8f0", "e5e7eb", "d7e0ea", "cbd5e1", "dde3ea", "e6ebf1", "eef2f7", "f1f5f9", "ddd", "ccc", "eee"]}

HEADER = """/* Rete di sicurezza del tema scuro per gli stili INLINE (style="...") nei template.
   Un colore scritto nell'attributo style vince su qualsiasi regola di classe: l'unico modo per
   ribaltarlo in tema scuro senza toccare centinaia di template e' intercettarlo con un selettore
   di attributo e !important. Vale SOLO sotto body.theme-dark: il tema chiaro resta identico.
   Nuovo codice: non scrivere colori inline, usare i token (--text, --text-mid, --surface...).
   Generato da tools/gen_dark_safety.py: modificare la mappa li', non questo file a mano. */
"""


def sels(prop, hexes):
    out = []
    for h in hexes:
        for sp in ("", " "):
            out.append(f'body.theme-dark [style*="{prop}:{sp}#{h}" i]')
    return ",\n".join(out)


def attr_sels(prop, hexes):
    """Solo i selettori di attributo, senza prefisso (per :is())."""
    return ",".join(f'[style*="{prop}:{sp}#{h}" i]' for h in hexes for sp in ("", " "))


def main(out_path):
    # sfondi inline che la sezione 2 sa ribaltare: solo su questi (o senza sfondo inline) il testo va ribaltato;
    # su uno sfondo colorato che resta com'e' (giallo, verde...) il testo scuro era giusto e deve restare
    mapped_bg = ",".join(attr_sels(p, h) for p in ("background", "background-color") for h in BG.values()) \
        + "," + ",".join(f'[style*="{v}" i]' for v in FAKE_VARS)
    lines = [HEADER, "/* 1. Testo scuro -> token del tema: se l'elemento non ha uno sfondo inline, oppure ha uno sfondo che la",
             "   sezione 2 ribalta. Il testo chiaro inline (es. #fff su bottoni colorati) non viene toccato. */"]
    for tok, hexes in TEXT.items():
        text_sels = attr_sels("color", hexes)
        lines.append(f'body.theme-dark :is({text_sels}):not([style*="background" i]),\n'
                     f'body.theme-dark :is({mapped_bg}):is({text_sels}){{color:{tok}!important}}')
    lines.append("")
    lines.append("/* 2. Sfondi chiari -> superficie del tema o tinta semantica traslucida. Prima i neutri (#fff), poi le tinte")
    lines.append("   (#fff7ed...): il selettore e' per sottostringa e a pari specificita' vince l'ultima regola. */")
    for tok, hexes in BG.items():
        lines.append(sels("background", hexes) + "," + sels("background-color", hexes)
                     + f"{{background-color:{tok}!important;background-image:none!important}}")
    lines.append("")
    lines.append("/* 2b. Variabili inesistenti con riserva chiara (var(--bg-alt,#f5f5f5) ecc.): non sono in theme.css, vince sempre la riserva. */")
    lines.append(",".join(f'body.theme-dark [style*="{v}" i]' for v in FAKE_VARS) + "{background-color:var(--surface-alt,#0f1b2d)!important;background-image:none!important}")
    lines.append("")
    lines.append("/* 3. Bordi chiari -> bordo del tema. */")
    for tok, hexes in BORDER.items():
        lines.append(",".join(sels(p, hexes) for p in ("border-color", "border", "border-top", "border-bottom", "border-left", "border-right"))
                     + f"{{border-color:{tok}!important}}")
    css = "\n".join(lines) + "\n"
    open(out_path, "w", encoding="utf-8").write(css)
    print("scritto", out_path, len(css), "byte")


if __name__ == "__main__":
    main(sys.argv[1])
