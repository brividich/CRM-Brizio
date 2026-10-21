"""Revisioni della struttura organizzativa: fotografia, emissione (solo MSM), confronto, PDF.

La fotografia contiene SOLO la struttura (processi, reparti, aree, ruoli, mansioni
con competenze richieste e mansioni di rischio): nessun nominativo, nessun livello
di persona. È il mansionario ufficiale che la Qualità emette e conserva.
"""
from __future__ import annotations

from io import BytesIO

from django.db import transaction
from django.db.models import Max

from ..models import AreaAziendale, CompetenzaSkm, Reparto, RuoloOperativo, StrutturaRevisione
from .mansionario_struttura import TIPI_MANSIONE

SIGLA_EMITTENTE = "MSM"
# Ogni voce si riconosce dal suo id (o dalla chiave della mansione), non dal nome:
# una rinomina è una modifica, non una voce tolta e una aggiunta.
SEZIONI = [
    ("processi", "Processi", "id"),
    ("reparti", "Reparti", "id"),
    ("aree", "Aree", "id"),
    ("ruoli", "Ruoli", "id"),
    ("mansioni", "Mansioni", "chiave"),
]
ETICHETTE = {
    "nome": "nome", "codice": "codice", "tipo": "tipo", "owner": "owner", "attivo": "attivo",
    "ruolo_responsabile": "ruolo responsabile", "aree": "aree", "reparto": "reparto", "sigla": "sigla",
    "classe": "diretto/indiretto", "organigramma": "organigramma", "riporta_a": "riporta a", "area": "area",
    "processo": "processo", "ruoli": "ruoli", "abilitazione_con_scadenza": "abilitazione con validità",
    "mansioni_rischio": "mansioni di rischio", "competenze": "competenze richieste",
}


def _et(ruolo) -> str:
    return ruolo.etichetta if ruolo is not None else ""


def fotografia() -> dict:
    from sistema_gestione.models import Processo

    from .mansionario_competenze import competenze

    processi = [{
        "id": p.pk, "nome": p.nome, "codice": p.codice, "tipo": p.get_tipo_display() if p.tipo else "",
        "owner": _et(p.ruolo_owner), "attivo": p.attivo,
    } for p in Processo.objects.select_related("ruolo_owner").filter(attivo=True).order_by("codice")]
    reparti = [{
        "id": r.pk, "nome": r.nome, "ruolo_responsabile": _et(r.ruolo_responsabile),
        "aree": sorted(a.nome for a in r.aree_aziendali.all() if a.is_active),
    } for r in Reparto.objects.filter(is_active=True).select_related("ruolo_responsabile")
        .prefetch_related("aree_aziendali").order_by("nome")]
    aree = [{
        "id": a.pk, "nome": a.nome, "reparto": a.reparto.nome if a.reparto_id else "",
        "ruolo_responsabile": _et(a.ruolo_responsabile),
    } for a in AreaAziendale.objects.filter(is_active=True).select_related("reparto", "ruolo_responsabile")
        .order_by("reparto__nome", "nome")]
    ruoli = [{
        "id": r.pk, "nome": r.nome, "sigla": r.sigla or "", "classe": r.get_classe_display() if r.classe else "",
        "organigramma": r.ambito_label, "riporta_a": r.riporta_a.nome if r.riporta_a_id else "",
    } for r in RuoloOperativo.objects.filter(is_active=True).select_related("ambito", "riporta_a").order_by("nome")]
    mansioni = []
    for m in (CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True)
              .select_related("area", "reparto", "processo_sgi", "asset")
              .prefetch_related("ruoli", "mansioni_rischio").order_by("display", "competenza_key")):
        mansioni.append({
            "chiave": m.competenza_key, "nome": m.nome, "tipo": m.get_tipo_display(),
            "area": m.area.nome if m.area_id else "", "reparto": m.reparto_effettivo,
            "processo": m.processo_sgi.nome if m.processo_sgi_id else "",
            "ruoli": sorted(_et(r) for r in m.ruoli.all()),
            "abilitazione_con_scadenza": m.abilitazione_con_scadenza,
            "mansioni_rischio": sorted(x.nome for x in m.mansioni_rischio.all()),
            "competenze": [{
                "nome": v.nome, "livello_minimo": v.livello_minimo, "bloccante": v.bloccante,
                "corso": str(v.corso) if v.corso_id else "", "qualifica": str(v.qualifica) if v.qualifica_id else "",
            } for v in competenze(m)],
        })
    return {"processi": processi, "reparti": reparti, "aree": aree, "ruoli": ruoli, "mansioni": mansioni}


def riepilogo(dati: dict) -> dict:
    out = {chiave: len(dati.get(chiave) or []) for chiave, _t, _k in SEZIONI}
    out["competenze"] = sum(len(m.get("competenze") or []) for m in dati.get("mansioni") or [])
    return out


def ultima() -> StrutturaRevisione | None:
    return StrutturaRevisione.objects.order_by("-numero").first()


def puo_emettere(user) -> bool:
    """Emette e approva SOLO chi ricopre oggi il ruolo MSM (decisione 21/10/2026)."""
    if not getattr(user, "is_authenticated", False):
        return False
    from core.operational_roles import get_roles_for_user

    return get_roles_for_user(user).filter(sigla=SIGLA_EMITTENTE).exists()


@transaction.atomic
def emetti(user, motivo: str) -> StrutturaRevisione:
    if not puo_emettere(user):
        raise PermissionError("Solo chi ricopre il ruolo MSM emette una revisione della struttura.")
    motivo = " ".join((motivo or "").split())[:500]
    if not motivo:
        raise ValueError("Scrivi il motivo della revisione.")
    dati = fotografia()
    prec = ultima()
    if prec is not None and prec.dati == dati:
        raise ValueError(f"Nessuna modifica rispetto alla Rev. {prec.numero}: non c'è niente da emettere.")
    numero = (StrutturaRevisione.objects.select_for_update().aggregate(n=Max("numero"))["n"] or 0) + 1
    nome = (user.get_full_name() or user.get_username()) if user is not None else ""
    return StrutturaRevisione.objects.create(numero=numero, emessa_da=user, emessa_da_nome=nome[:200],
                                             motivo=motivo, dati=dati, riepilogo=riepilogo(dati))


def _descrivi(valore) -> str:
    if isinstance(valore, bool):
        return "sì" if valore else "no"
    if isinstance(valore, list):
        if valore and isinstance(valore[0], dict):
            return f"{len(valore)} voci"
        return ", ".join(str(v) for v in valore) or "—"
    return str(valore) if valore not in ("", None) else "—"


def confronto(prima: dict, dopo: dict) -> list[dict]:
    """Differenze sezione per sezione: aggiunte, tolte, cambiate (campo per campo)."""
    out = []
    for chiave, titolo, id_campo in SEZIONI:
        # Fotografie senza id (formato più vecchio): si ripiega sul nome.
        a = {x.get(id_campo) or x.get("nome"): x for x in (prima or {}).get(chiave) or []}
        b = {x.get(id_campo) or x.get("nome"): x for x in (dopo or {}).get(chiave) or []}
        aggiunte = [b[k] for k in b.keys() - a.keys()]
        tolte = [a[k] for k in a.keys() - b.keys()]
        cambiate = []
        for k in sorted(a.keys() & b.keys()):
            campi = [{"campo": ETICHETTE.get(c, c), "prima": _descrivi(a[k].get(c)), "dopo": _descrivi(b[k].get(c))}
                     for c in sorted(set(a[k]) | set(b[k]))
                     if c not in (id_campo, "id", "chiave") and a[k].get(c) != b[k].get(c)]
            if campi:
                cambiate.append({"voce": b[k].get("nome") or str(k), "campi": campi})
        if aggiunte or tolte or cambiate:
            out.append({
                "sezione": titolo,
                "aggiunte": sorted((x.get("nome") or str(x.get(id_campo)) for x in aggiunte), key=str.casefold),
                "tolte": sorted((x.get("nome") or str(x.get(id_campo)) for x in tolte), key=str.casefold),
                "cambiate": cambiate,
            })
    return out


def pdf(revisione: StrutturaRevisione) -> bytes:
    """Mansionario ufficiale della revisione (dalla fotografia, mai dalla struttura viva)."""
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading
    from django.utils.html import escape

    d = revisione.dati or {}
    theme = PdfTheme.from_branding()
    st = build_styles(theme)
    buf = BytesIO()
    titolo = f"Struttura organizzativa e mansionario - Rev. {revisione.numero}"
    doc = make_document(buf, title=titolo, landscape=True)
    P = lambda t, s="cell": Paragraph(escape(str(t or "")), st[s])  # noqa: E731
    story = [
        Paragraph("Struttura organizzativa e mansionario", st["title"]),
        Paragraph(f"Rev. {revisione.numero} del {revisione.emessa_il:%d/%m/%Y} - emessa da "
                  f"{escape(revisione.emessa_da_nome or '-')} (MSM)", st["subtitle"]),
        Paragraph(f"Motivo: {escape(revisione.motivo)}", st["body"]),
        Spacer(1, 4 * mm),
    ]
    story += section_heading("Processi", theme, st)
    story.append(data_table([[P(x, "table_header") for x in ("Codice", "Processo", "Tipo", "Owner")]] + [
        [P(p["codice"]), P(p["nome"]), P(p["tipo"]), P(p["owner"])] for p in d.get("processi") or []],
        theme, col_widths=[30 * mm, 110 * mm, 35 * mm, 80 * mm]))
    story += section_heading("Reparti e aree", theme, st)
    righe = [[P(x, "table_header") for x in ("Reparto", "Responsabile (ruolo)", "Area", "Responsabile area (ruolo)")]]
    aree_per = {}
    for a in d.get("aree") or []:
        aree_per.setdefault(a["reparto"], []).append(a)
    for r in d.get("reparti") or []:
        for i, a in enumerate(aree_per.get(r["nome"]) or [{"nome": "", "ruolo_responsabile": ""}]):
            righe.append([P(r["nome"] if i == 0 else ""), P(r["ruolo_responsabile"] if i == 0 else ""),
                          P(a["nome"]), P(a["ruolo_responsabile"])])
    story.append(data_table(righe, theme, col_widths=[45 * mm, 70 * mm, 60 * mm, 80 * mm]))
    story += section_heading("Ruoli", theme, st)
    story.append(data_table([[P(x, "table_header") for x in ("Sigla", "Ruolo", "Diretto/indiretto", "Organigramma",
                                                              "Riporta a")]] + [
        [P(r["sigla"]), P(r["nome"]), P(r["classe"]), P(r["organigramma"]), P(r["riporta_a"])]
        for r in d.get("ruoli") or []], theme, col_widths=[22 * mm, 75 * mm, 35 * mm, 55 * mm, 68 * mm]))
    story.append(PageBreak())
    story += section_heading("Mansioni", theme, st)
    righe = [[P(x, "table_header") for x in ("Area", "Mansione", "Ruoli", "Processo", "Mansioni di rischio",
                                             "Competenze richieste")]]
    for m in sorted(d.get("mansioni") or [], key=lambda m: (m["reparto"], m["area"], m["nome"])):
        comp = "; ".join(f"{c['nome']} ({c['livello_minimo']}{', bloccante' if c['bloccante'] else ''})"
                         for c in m.get("competenze") or [])
        nome = m["nome"] + (" [abilitazione con validità]" if m.get("abilitazione_con_scadenza") else "")
        righe.append([P(m["area"] or m["reparto"]), P(nome), P(", ".join(m["ruoli"])), P(m["processo"]),
                      P(", ".join(m["mansioni_rischio"])), P(comp or "-")])
    story.append(data_table(righe, theme, col_widths=[28 * mm, 70 * mm, 40 * mm, 35 * mm, 35 * mm, 50 * mm]))
    cb = header_footer_callback(theme, title=titolo, subtitle="Documento controllato - Qualità")
    doc.build(story, onFirstPage=cb, onLaterPages=cb)
    return buf.getvalue()
