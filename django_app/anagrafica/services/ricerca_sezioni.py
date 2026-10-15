"""Ricerca di Anagrafica: una casella su tutto il modulo (dashboard) e una per sezione.

Un solo motore, più «ambiti». Ogni ambito è un elenco di gruppi di risultati
(persone, posizioni, tipi di qualifica…); ogni gruppo entra solo se l'utente ha il
permesso della sezione da cui viene, con gli stessi cancelli delle pagine. La
ricerca serve a «saltare» a una scheda, non è un motore full-text: contiene, senza
maiuscole, limitata in righe.

Privacy: per le visite si mostrano tipo e scadenza, mai esito o giudizio; per
l'amministrazione solo nomi e collegamenti, mai importi.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.urls import reverse

from core import naming

MIN_CARATTERI = 2
LIMITE = 25

AMBITI = {
    "tutto": "tutto il modulo Anagrafica",
    "persone": "Persone",
    "ingressi": "Ingressi",
    "qualifiche": "Qualifiche",
    "visite": "Visite mediche",
    "amministrazione": "Amministrazione",
    "report": "Report",
}


@dataclass
class Gruppo:
    chiave: str
    titolo: str
    icona: str
    voci: list[dict] = field(default_factory=list)
    altro_url: str = ""  # «cerca qui» nella ricerca dedicata della sezione


def _voce(titolo: str, url: str, meta: str = "", icona: str = "") -> dict:
    return {"t": titolo, "url": url, "m": meta, "icona": icona}


def _persone_visibili(request) -> list[dict]:
    from ..views import build_dipendenti_rows

    return build_dipendenti_rows(request, apply_filters=False)


def _match_persona(r: dict, ql: str) -> bool:
    return any(ql in str(r.get(k) or "").casefold()
               for k in ("nome", "cognome", "aliasusername", "matricola", "mansione", "reparto")) or (
        ql in naming.nome_completo(r.get("nome"), r.get("cognome")).casefold())


def _persone_trovate(request, ql: str) -> list[dict]:
    righe = [r for r in _persone_visibili(request) if _match_persona(r, ql)]
    return righe[:LIMITE]


# ── Gruppi ───────────────────────────────────────────────────────────────────

def _g_persone(request, q, ql, *, url_scheda="anagrafica:dipendente_detail", ancora="", meta_extra="") -> Gruppo:
    g = Gruppo("persone", "Dipendenti", "i-users")
    for r in _persone_trovate(request, ql):
        lid = int(r.get("id") or 0)
        if lid <= 0:
            continue
        meta = " · ".join(x for x in (str(r.get("mansione") or "").strip(), str(r.get("reparto") or "").strip(), meta_extra) if x)
        g.voci.append(_voce(naming.nome_completo(r.get("nome"), r.get("cognome")),
                            reverse(url_scheda, args=[lid]) + ancora, meta, "i-users"))
    return g


def _g_ingressi(request, q, ql) -> list[Gruppo]:
    from ..models_recruiting import Candidato, PosizioneAperta
    from ..views_recruiting import _can_view_recruiting

    if not _can_view_recruiting(request):
        return []
    pos = Gruppo("posizioni", "Posizioni aperte", "i-building")
    for p in (PosizioneAperta.objects.filter(Q(titolo__icontains=q) | Q(reparto__icontains=q) | Q(mansione__icontains=q))
              .order_by("-data_richiesta")[:LIMITE]):
        pos.voci.append(_voce(p.titolo, reverse("anagrafica:recruiting_posizione_detail", args=[p.pk]),
                              " · ".join(x for x in (p.reparto, p.get_stato_display(),
                                                     f"richiesta il {p.data_richiesta:%d-%m-%Y}") if x), "i-building"))
    cand = Gruppo("candidati", "Candidati", "i-users")
    filtro = (Q(cognome__icontains=q) | Q(nome__icontains=q) | Q(mansione_cercata__icontains=q)
              | Q(codice_riferimento__icontains=q))
    parti = q.split()
    if len(parti) >= 2:  # «Rossi Mario» o «Mario Rossi»
        filtro |= (Q(cognome__icontains=parti[0]) & Q(nome__icontains=parti[-1])) | (
            Q(nome__icontains=parti[0]) & Q(cognome__icontains=parti[-1]))
    for c in Candidato.objects.filter(filtro).exclude(stato=Candidato.STATO_ANNULLATO).order_by("-id")[:LIMITE]:
        nome = naming.nome_completo(c.nome, c.cognome) or f"Candidato {c.codice_riferimento or c.pk}"
        cand.voci.append(_voce(nome, reverse("anagrafica:recruiting_detail", args=[c.pk]),
                               " · ".join(x for x in (c.mansione_cercata, c.get_stato_display()) if x), "i-users"))
    return [pos, cand]


def _g_qualifiche(request, q, ql) -> list[Gruppo]:
    from ..models import DipendenteQualifica, TipoQualifica

    tipi = Gruppo("tipi_qualifica", "Tipi di qualifica", "i-cap")
    scad = reverse("anagrafica:qualifiche_scadenzario")
    for t in TipoQualifica.objects.filter(Q(nome__icontains=q) | Q(descrizione__icontains=q)).order_by("nome")[:LIMITE]:
        tipi.voci.append(_voce(t.nome, f"{scad}?tipo={t.pk}&stato=tutte",
                               t.get_categoria_display() + (f" · validità {t.durata_mesi} mesi" if t.durata_mesi else ""), "i-cap"))
    # Persone trovate per nome, con le loro qualifiche (nome del tipo e scadenza).
    abil = Gruppo("abilitati", "Persone e qualifiche", "i-award")
    persone = {int(r.get("id") or 0): r for r in _persone_trovate(request, ql)}
    per_persona: dict[int, list[str]] = {}
    for dq in (DipendenteQualifica.objects.filter(legacy_anagrafica_id__in=list(persone)).select_related("tipo")
               .order_by("tipo__nome")):
        per_persona.setdefault(dq.legacy_anagrafica_id, []).append(
            dq.tipo.nome + (f" (scade {dq.data_scadenza:%d-%m-%Y})" if dq.data_scadenza else ""))
    for lid, quali in per_persona.items():
        r = persone[lid]
        abil.voci.append(_voce(naming.nome_completo(r.get("nome"), r.get("cognome")),
                               reverse("anagrafica:dipendente_detail", args=[lid]), "; ".join(quali[:3])
                               + (f" e altre {len(quali) - 3}" if len(quali) > 3 else ""), "i-award"))
    return [tipi, abil]


def _g_visite(request, q, ql) -> list[Gruppo]:
    from ..models import TipoVisitaMedica, VisitaMedica
    from ..services.visite import ultime_visite_correnti_ids
    from ..views import _can_view_visite_mediche

    if not _can_view_visite_mediche(request):
        return []
    tipi = Gruppo("tipi_visita", "Tipi di visita", "i-pill")
    base = reverse("anagrafica:visite_mediche_dashboard")
    for t in TipoVisitaMedica.objects.filter(nome__icontains=q, is_active=True).order_by("nome")[:LIMITE]:
        tipi.voci.append(_voce(t.nome, f"{base}#tipo-row-{t.pk}",
                               (f"ogni {t.durata_mesi} mesi" if t.durata_mesi else "senza periodicità")
                               + ("" if t.obbligatoria else " · facoltativa"), "i-pill"))
    pers = Gruppo("persone_visite", "Persone e scadenze delle visite", "i-users")
    persone = {int(r.get("id") or 0): r for r in _persone_trovate(request, ql)}
    per_persona: dict[int, list[str]] = {}
    if persone:
        correnti = ultime_visite_correnti_ids(legacy_ids=list(persone))
        for v in (VisitaMedica.objects.filter(legacy_anagrafica_id__in=list(persone)).select_related("tipo")
                  .order_by("data_scadenza")):
            if v.pk in correnti:
                per_persona.setdefault(v.legacy_anagrafica_id, []).append(
                    v.tipo.nome + (f" (scade {v.data_scadenza:%d-%m-%Y})" if v.data_scadenza else ""))
    for lid, r in persone.items():
        visite = per_persona.get(lid, [])
        pers.voci.append(_voce(naming.nome_completo(r.get("nome"), r.get("cognome")),
                               reverse("anagrafica:dipendente_detail", args=[lid]) + "#visite-mediche",
                               "; ".join(visite[:2]) + (f" e altre {len(visite) - 2}" if len(visite) > 2 else "")
                               if visite else "nessuna visita registrata", "i-pill"))
    return [tipi, pers]


def _g_amministrazione(request, q, ql) -> list[Gruppo]:
    from ..models import ImportazioneCedolini, ImportazioneRetributiva
    from ..views import _check_hr_permission

    if not _check_hr_permission(request):
        return []
    pers = _g_persone(request, q, ql, url_scheda="anagrafica:dipendente_retribuzioni", meta_extra="retribuzioni")
    pers.titolo = "Retribuzioni del dipendente"
    imp = Gruppo("import", "Import", "i-download")
    for i in ImportazioneRetributiva.objects.filter(file_nome__icontains=q).order_by("-data_importazione")[:10]:
        imp.voci.append(_voce(i.file_nome, reverse("anagrafica:retribuzioni_import"),
                              f"retribuzioni {i.data_competenza:%m/%Y} · {i.righe_ok} righe", "i-download"))
    for i in ImportazioneCedolini.objects.filter(file_nome__icontains=q).order_by("-data_importazione")[:10]:
        imp.voci.append(_voce(i.file_nome, reverse("anagrafica:cedolini_import"),
                              f"cedolini {i.data_competenza:%m/%Y} · {i.righe_ok} righe", "i-download"))
    return [pers, imp]


def _g_report(request, q, ql) -> list[Gruppo]:
    from ..models_reportistica import ReportGenerato, ReportModello
    from ..reportistica.permessi import can_view

    if not can_view(request):
        return []
    mod = Gruppo("modelli", "Modelli di report", "i-grid")
    for m in (ReportModello.objects.filter(is_active=True)
              .filter(Q(nome__icontains=q) | Q(descrizione__icontains=q) | Q(destinatario__icontains=q))
              .order_by("nome")[:LIMITE]):
        mod.voci.append(_voce(m.nome, reverse("anagrafica:reportistica_genera", args=[m.pk]),
                              " · ".join(x for x in (", ".join(m.norme or []), m.destinatario) if x) or "modello", "i-grid"))
    arc = Gruppo("archivio", "Archivio dei generati", "i-doc")
    for d in (ReportGenerato.objects.defer("contenuto")
              .filter(Q(titolo__icontains=q) | Q(destinatario__icontains=q) | Q(modello_nome__icontains=q))
              .order_by("-generato_il")[:LIMITE]):
        arc.voci.append(_voce(d.titolo, reverse("anagrafica:reportistica_archivio_download", args=[d.pk]),
                              " · ".join(x for x in (f"{d.generato_il:%d-%m-%Y}", d.destinatario) if x), "i-doc"))
    return [mod, arc]


def _g_formazione(request, q, ql) -> list[Gruppo]:
    from ..models_formazione import TrainingCourse
    from ..views import _can_view_formazione

    if not _can_view_formazione(request):
        return []
    g = Gruppo("corsi", "Corsi di formazione", "i-book",
               altro_url=reverse("anagrafica:formazione_ricerca") + "?q=")
    for c in TrainingCourse.objects.filter(Q(titolo__icontains=q) | Q(codice__icontains=q)).order_by("titolo")[:LIMITE]:
        g.voci.append(_voce(c.titolo, reverse("anagrafica:formazione_corso_detail", args=[c.pk]), c.codice, "i-book"))
    return [g]


def _g_sicurezza(request, q, ql) -> list[Gruppo]:
    from ..models_mansioni_rischio import MansioneRischio
    from ..views import _can_view_formazione

    if not _can_view_formazione(request):  # stesso cancello del cruscotto sicurezza
        return []
    g = Gruppo("mansioni_rischio", "Mansioni di rischio", "i-alert-tri",
               altro_url=reverse("anagrafica:sicurezza_ricerca") + "?q=")
    for mr in MansioneRischio.objects.filter(Q(nome__icontains=q) | Q(codice__icontains=q)).order_by("nome")[:LIMITE]:
        g.voci.append(_voce(mr.nome, reverse("anagrafica:mansione_rischio_dettaglio", args=[mr.pk]),
                            mr.codice + (f" · rischio {mr.get_livello_rischio_dvr_display().lower()}"
                                         if mr.livello_rischio_dvr else ""), "i-alert-tri"))
    return [g]


def cerca(request, q: str, ambito: str = "tutto") -> list[Gruppo]:
    """Gruppi non vuoti per ``q`` nell'``ambito`` (vedi ``AMBITI``), già filtrati per permesso."""
    q = (q or "").strip()
    if len(q) < MIN_CARATTERI:
        return []
    ql = q.casefold()
    if ambito not in AMBITI:
        ambito = "tutto"
    gruppi: list[Gruppo] = []
    if ambito == "persone":
        gruppi = [_g_persone(request, q, ql)]
    elif ambito == "ingressi":
        gruppi = _g_ingressi(request, q, ql)
    elif ambito == "qualifiche":
        gruppi = _g_qualifiche(request, q, ql)
    elif ambito == "visite":
        gruppi = _g_visite(request, q, ql)
    elif ambito == "amministrazione":
        gruppi = _g_amministrazione(request, q, ql)
    elif ambito == "report":
        gruppi = _g_report(request, q, ql)
    else:  # tutto il modulo: un gruppo per sezione, nessun dato di dettaglio
        gruppi = [_g_persone(request, q, ql)]
        gruppi += _g_ingressi(request, q, ql)
        gruppi += _g_formazione(request, q, ql)
        gruppi += _g_qualifiche(request, q, ql)[:1]
        gruppi += _g_sicurezza(request, q, ql)
        gruppi += _g_visite(request, q, ql)[:1]
        gruppi += _g_report(request, q, ql)
    return [g for g in gruppi if g.voci]
