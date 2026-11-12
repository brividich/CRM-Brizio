"""CN-SGI: servizi della scheda e della libreria (secondo giro di UI).

- :func:`differenze`: «Cosa cambia in questa revisione», per paragrafo, dal testo estratto;
- :func:`preferiti_di` / :func:`lette_da`: stella «I miei documenti» e spunta «già letta»;
- :func:`tipo_documento`: famiglia del documento dal codice (filtri dello scaffale);
- :func:`con_glossario`: termini del glossario tecnico evidenziati negli estratti;
- :func:`qr_svg`: QR delle etichette da affiggere in reparto;
- :func:`da_rivedere` / :func:`citati_mancanti`: controlli per chi gestisce;
- :func:`mappa`: posizioni della piccola mappa «cita / è citato da».

Tutto in sola lettura, niente file aperti: lavora sul database e sul testo già estratto.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

# ---------------------------------------------------------------------------
# Cosa cambia in questa revisione
# ---------------------------------------------------------------------------

_TITOLO_PARAGRAFO = re.compile(r"^[ \t]*(?:#+[ \t]*)?(§?[ \t]*\d+(?:\.\d+){0,3})[.)]?[ \t]+(\S.*)$", re.MULTILINE)
SOGLIA_UGUALE = 0.985
MAX_PARAGRAFI = 40


@dataclass
class Paragrafo:
    numero: str
    titolo: str
    testo: str


@dataclass
class Cambiamento:
    tipo: str  # aggiunto | tolto | modificato
    numero: str
    titolo: str
    righe: list = field(default_factory=list)  # [(segno, testo)] per i modificati


def paragrafi(testo: str) -> list[Paragrafo]:
    """Il testo diviso nei paragrafi numerati (§1, §4.2…); quello che precede il primo è «Inizio»."""
    testo = testo or ""
    trovati = list(_TITOLO_PARAGRAFO.finditer(testo))
    out = []
    if not trovati:
        return [Paragrafo("", "Testo", testo.strip())] if testo.strip() else []
    if trovati[0].start() > 0 and testo[: trovati[0].start()].strip():
        out.append(Paragrafo("", "Inizio", testo[: trovati[0].start()].strip()))
    for i, m in enumerate(trovati):
        fine = trovati[i + 1].start() if i + 1 < len(trovati) else len(testo)
        out.append(Paragrafo(m.group(1).replace(" ", "").lstrip("§"), m.group(2).strip()[:120], testo[m.start():fine].strip()))
    return out


def _normale(testo: str) -> str:
    return re.sub(r"\s+", " ", testo or "").strip().lower()


def differenze(testo_vecchio: str, testo_nuovo: str) -> list[Cambiamento]:
    """Paragrafi aggiunti, tolti e modificati fra due revisioni (confronto per numero, poi per titolo)."""
    vecchi = paragrafi(testo_vecchio)
    nuovi = paragrafi(testo_nuovo)
    chiave = lambda p: p.numero or _normale(p.titolo)  # noqa: E731
    per_chiave = {chiave(p): p for p in vecchi}
    usati = set()
    out: list[Cambiamento] = []
    for p in nuovi:
        k = chiave(p)
        prima = per_chiave.get(k)
        if prima is None:
            # Stesso titolo con un altro numero: paragrafo rinumerato, non nuovo.
            prima = next((v for v in vecchi if chiave(v) not in usati and _normale(v.titolo) == _normale(p.titolo)), None)
        if prima is None:
            out.append(Cambiamento("aggiunto", p.numero, p.titolo))
            continue
        usati.add(chiave(prima))
        a, b = _normale(prima.testo), _normale(p.testo)
        if a == b or difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= SOGLIA_UGUALE:
            continue
        righe = []
        frasi_a = re.split(r"(?<=[.;:])\s+|\n+", prima.testo)
        frasi_b = re.split(r"(?<=[.;:])\s+|\n+", p.testo)
        for riga in difflib.ndiff([f.strip() for f in frasi_a if f.strip()], [f.strip() for f in frasi_b if f.strip()]):
            if riga[:2] in ("- ", "+ "):
                righe.append(("tolto" if riga[0] == "-" else "aggiunto", riga[2:][:400]))
        out.append(Cambiamento("modificato", p.numero, p.titolo, righe[:12]))
    for v in vecchi:
        if chiave(v) not in usati and chiave(v) not in {chiave(p) for p in nuovi}:
            out.append(Cambiamento("tolto", v.numero, v.titolo))
    return out[:MAX_PARAGRAFI]


def revisione_precedente(doc, rev):
    """La revisione prima di quella in vigore che ha il testo estratto, o None."""
    altre = [r for r in doc.revisions.all() if r.pk != rev.pk and r.revision_date and rev.revision_date and r.revision_date <= rev.revision_date]
    altre.sort(key=lambda r: (r.revision_date, r.pk), reverse=True)
    for r in altre:
        try:
            if r.testo_estratto and r.testo_estratto.testo:
                return r
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Preferiti, letture, tipi
# ---------------------------------------------------------------------------


def preferiti_di(user) -> list[int]:
    from procedure_refresh.models import SgiPreferito

    if not getattr(user, "is_authenticated", False):
        return []
    return list(SgiPreferito.objects.filter(user=user).values_list("documento_id", flat=True))


def lette_da(user, docs) -> set[int]:
    """Documenti di cui l'utente ha confermato la lettura della revisione in vigore."""
    from procedure_refresh.models import AssignmentStatus, ProcedureAssignment

    if not getattr(user, "is_authenticated", False):
        return set()
    per_rev = {d.rev.pk: d.pk for d in docs if getattr(d, "rev", None)}
    if not per_rev:
        return set()
    righe = ProcedureAssignment.objects.filter(
        user=user, status=AssignmentStatus.READ_CONFIRMED, revision_id__in=list(per_rev)
    ).values_list("revision_id", flat=True)
    return {per_rev[r] for r in righe}


TIPI = (
    ("manuale", "Manuali"),
    ("mt", "MT procedure"),
    ("mtsi", "MTSI istruzioni"),
    ("mod", "MOD modelli"),
    ("piano", "Piani qualità"),
    ("altro", "Altri"),
)


def tipo_documento(doc) -> str:
    codice = (doc.code or "").upper().replace(".", " ")
    if codice.startswith("MTSI"):
        return "mtsi"
    if codice.startswith("MT"):
        return "mt"
    if codice.startswith("MOD"):
        return "mod"
    if codice.startswith(("IDOR", "MQ", "MO-ID", "MSG")) or "manuale" in (doc.title or "").lower():
        return "manuale"
    if codice.startswith(("PDQ", "PQ")) or "piano" in (doc.title or "").lower() and "qualit" in (doc.title or "").lower():
        return "piano"
    return "altro"


# ---------------------------------------------------------------------------
# Glossario negli estratti
# ---------------------------------------------------------------------------


def _termini() -> list[tuple[str, str, str, int]]:
    dati = cache.get("cnsgi_glossario_v1")
    if dati is not None:
        return dati
    dati = []
    try:
        from glossario_tecnico.models import Termine

        for t in Termine.objects.filter(stato=Termine.VALIDATO).only("pk", "termine", "definizione"):
            nome = (t.termine or "").strip()
            if len(nome) < 3:
                continue
            dati.append((nome.lower(), nome, re.sub(r"\s+", " ", t.definizione or "")[:220], t.pk))
    except Exception:
        dati = []
    dati.sort(key=lambda x: -len(x[0]))
    cache.set("cnsgi_glossario_v1", dati, 600)
    return dati


def con_glossario(testo: str):
    """Testo dell'estratto con i termini del glossario come <abbr> (spiegazione al passaggio del mouse)."""
    sicuro = str(escape(testo or ""))
    termini = _termini()
    if not termini or not sicuro:
        return mark_safe(sicuro)
    usati = 0
    for basso, _nome, definizione, _pk in termini:
        if usati >= 4:
            break
        rx = re.compile(r"(?<![\w&])(" + re.escape(str(escape(basso))) + r")(?![\w;])", re.IGNORECASE)
        if not rx.search(sicuro):
            continue
        titolo = str(escape(definizione))
        sicuro = rx.sub(lambda m: f'<abbr class="cn-gloss" title="{titolo}">{m.group(1)}</abbr>', sicuro, count=1)
        usati += 1
    return mark_safe(sicuro)


# ---------------------------------------------------------------------------
# QR delle etichette
# ---------------------------------------------------------------------------


def qr_svg(testo: str) -> str:
    """QR in SVG (stringa), da mettere nella pagina delle etichette. Vuoto se la libreria manca."""
    try:
        import qrcode
        import qrcode.image.svg
    except Exception:
        return ""
    img = qrcode.make(testo, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    svg = img.to_string(encoding="unicode")
    return re.sub(r"^<\?xml[^>]*>\s*", "", svg)


# ---------------------------------------------------------------------------
# Per chi gestisce: da rivedere
# ---------------------------------------------------------------------------

ANNI_DA_RIVEDERE = 3


def da_rivedere(docs, anni: int = ANNI_DA_RIVEDERE) -> list:
    limite = timezone.localdate() - timedelta(days=365 * anni)
    vecchi = [d for d in docs if d.rev.revision_date and d.rev.revision_date < limite]
    return sorted(vecchi, key=lambda d: d.rev.revision_date)


def citati_mancanti(limite: int = 60) -> list[dict]:
    """Codici citati nel testo dei documenti in vigore che nella cartella SGI non esistono."""
    from procedure_refresh.models import SgiRiferimento

    gruppi: dict[str, dict] = {}
    righe = (
        SgiRiferimento.objects.filter(risolto=False, da_revisione__is_current=True, da_revisione__document__is_active=True)
        .exclude(tipo_risoluzione="famiglia")
        .select_related("da_revisione__document")
    )
    for r in righe:
        g = gruppi.setdefault(r.codice_citato, {"codice": r.codice_citato, "da": [], "volte": 0})
        g["volte"] += r.occorrenze
        d = r.da_revisione.document
        if all(x.pk != d.pk for x in g["da"]):
            g["da"].append(d)
    return sorted(gruppi.values(), key=lambda g: (-len(g["da"]), g["codice"]))[:limite]


# ---------------------------------------------------------------------------
# Mappa «cita / è citato da»
# ---------------------------------------------------------------------------

MAX_NODI_LATO = 7


def mappa(codice: str, cita: list[dict], citato_da: list[dict]) -> dict | None:
    """Coordinate per un SVG 560×H: il documento al centro, a sinistra chi lo cita, a destra cosa cita."""
    sinistra = [c for c in citato_da if c.get("doc")][:MAX_NODI_LATO]
    destra = [c for c in cita if c.get("doc")][:MAX_NODI_LATO]
    if not sinistra and not destra:
        return None
    righe = max(len(sinistra), len(destra), 1)
    altezza = max(120, 40 * righe + 20)
    centro_y = altezza / 2

    def colonna(elenco, x):
        if not elenco:
            return []
        passo = altezza / (len(elenco) + 1)
        return [{"x": x, "y": int(round(passo * (i + 1))), "codice": c["codice"], "titolo": c["titolo"], "pk": c["doc"].pk}
                for i, c in enumerate(elenco)]

    return {
        "larghezza": 560,
        "altezza": int(altezza),
        "centro": {"x": 280, "y": int(round(centro_y)), "codice": codice},
        "sinistra": colonna(sinistra, 70),
        "destra": colonna(destra, 490),
        "altri_sinistra": max(0, len([c for c in citato_da if c.get("doc")]) - len(sinistra)),
        "altri_destra": max(0, len([c for c in cita if c.get("doc")]) - len(destra)),
    }
