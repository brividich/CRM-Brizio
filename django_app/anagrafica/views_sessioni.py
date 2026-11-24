"""Sessioni formative: elenco, dettaglio, apertura dalla richiesta, valutazione, firme, chiusura.

Stesso permesso di rotta delle richieste («Il mio team»); che cosa si vede e che cosa si può fare
lo decide ``services/sessioni.py`` a ogni richiesta, lato server. I file caricati (registro MOD.040,
foglio firmato) si scaricano solo da qui, dopo lo stesso controllo.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import TrainingCourse
from .models_richieste import RichiestaCompetenze as R
from .models_sessioni import SessioneFormativa as S, SessioneRiga as Riga
from .services import esplora_semplice
from .services import richieste as rq
from .services import sessioni as svc
from .views_richieste import _int, _notifica

logger = logging.getLogger(__name__)
MODULE = "anagrafica"
ESTENSIONI_FILE = (".pdf", ".jpg", ".jpeg", ".png")
MAX_FILE = 10 * 1024 * 1024
FILTRI = {
    "aperte": ("Aperte", lambda s: s.aperta),
    "positive": ("Chiuse positive", lambda s: s.stato == S.STATO_POSITIVA),
    "negative": ("Chiuse negative", lambda s: s.stato == S.STATO_NEGATIVA),
}


def _file(request, campo: str):
    f = request.FILES.get(campo)
    if not f:
        return None
    if not f.name.lower().endswith(ESTENSIONI_FILE) or f.size > MAX_FILE:
        raise svc.SessioneNonValida("Il file deve essere PDF o un'immagine (JPG, PNG) fino a 10 MB.")
    return f


def _capo(persona_id: int) -> int | None:
    try:
        from .services import capo_team

        capo = capo_team.capo_di(persona_id)
        return getattr(capo, "legacy_id", None)
    except Exception:
        logger.exception("Sessioni: capo non trovato")
        return None


def _scheda(s, riga: dict) -> dict:
    r = s.richiesta
    campi = [("Sessione", s.codice), ("Persona", riga["persona"]), ("Richiesta", f"{r.codice} · {r.get_tipo_display()}")]
    if r.mansione_id:
        campi.append(("Mansione", r.mansione.nome))
    if r.competenza_id:
        campi.append(("Competenza", r.competenza.nome))
    parola = esplora_semplice.PAROLE_LIVELLO.get(r.livello, "")
    campi += [("Livello da raggiungere", f"{r.livello} · {parola}" if r.livello else "—"), ("Competenze valutate", f"{riga['fatte']} di {riga['totale']}"),
              ("Stato", s.get_stato_display()), ("Tocca a", riga["tocca_a"] or "Nessuno"),
              ("Aperta da", f"{s.aperta_da_nome} · {timezone.localtime(s.aperta_il):%d/%m/%Y}")]
    url = reverse("anagrafica:sessione", args=[s.pk])
    return {"campi": campi, "azioni": [{"nome": "Apri la sessione", "url": url}],
            "collegate": [{"nome": f"Richiesta {r.codice}", "spiega": "Chi l'ha chiesta e chi l'ha approvata",
                           "url": reverse("anagrafica:richiesta", args=[r.pk])}]}


@login_required
def elenco(request):
    a = rq.attore(request)
    tutte = list(svc.visibili(a).prefetch_related("righe"))
    filtro = request.GET.get("stato") or ""
    conteggi = {k: sum(1 for s in tutte if regola(s)) for k, (_, regola) in FILTRI.items()}
    scelte = [s for s in tutte if FILTRI[filtro][1](s)] if filtro in FILTRI else tutte
    if filtro not in FILTRI:
        filtro = ""
    righe = svc.righe(scelte[:300])
    for x in righe:
        x["scheda"] = _scheda(x["sessione"], x)
    chiesta = _int(request.GET.get("sessione"))
    dati = svc.da_fare(a)
    da_fare = [x for x in (
        {"n": len(dati["da_aprire"]), "titolo": "Sessioni da aprire", "sotto": "Richieste approvate senza sessione"},
        {"n": len(dati["da_valutare"]), "titolo": "Competenze da valutare", "sotto": "Sessioni con righe aperte"},
        {"n": len(dati["da_firmare"]), "titolo": "Sessioni da firmare", "sotto": "Tutte le competenze valutate"},
        {"n": len(dati["da_firmare_io"]), "titolo": "Da firmare tu", "sotto": "La tua formazione è pronta"},
        {"n": len(dati["da_chiudere"]), "titolo": "Sessioni da chiudere", "sotto": "Firmate da tutti"},
    ) if x["n"]]
    from .models_sessioni import ContatoreMatricola
    from .views import _helpers

    return render(request, "anagrafica/pages/sessioni_elenco.html", {
        "contatori": list(ContatoreMatricola.objects.all()) if _helpers._is_anagrafica_admin(request) else [],
        "righe": righe, "filtro": filtro, "n_tutte": len(tutte),
        "filtri": [{"chiave": k, "nome": n, "n": conteggi[k]} for k, (n, _) in FILTRI.items()],
        "scelta": next((x for x in righe if x["sessione"].pk == chiesta), righe[0] if righe else None),
        "da_fare": da_fare, "da_aprire": dati["da_aprire"],
    })


def _sessione_visibile(request, pk: int):
    a = rq.attore(request)
    s = get_object_or_404(S.objects.select_related("richiesta__mansione", "richiesta__competenza"), pk=pk)
    if not svc.puo_vedere(a, s):
        raise Http404
    return a, s


@login_required
def dettaglio(request, pk: int):
    a, s = _sessione_visibile(request, pk)
    persona = svc.righe([s])[0]
    nomi = persona["nomi"]
    righe = []
    for riga in s.righe.select_related("corso", "area", "edizione"):
        righe.append({"r": riga, "persona": nomi.get(riga.legacy_anagrafica_id, ""),
                      "richiesto": esplora_semplice.livello(riga.livello_richiesto),
                      "raggiunto": esplora_semplice.livello(riga.livello_raggiunto),
                      "oggi": esplora_semplice.livello(riga.livello_oggi),
                      "motivo_non_valuta": svc.motivo_non_valuta(a, riga)})
    return render(request, "anagrafica/pages/sessione_dettaglio.html", {
        "s": s, "r": s.richiesta, "persona": persona["persona"], "tocca_a": persona["tocca_a"],
        "passi": svc.passi(s), "righe": righe, "fatte": persona["fatte"], "totale": persona["totale"],
        "livello": esplora_semplice.livello(s.richiesta.livello), "legenda": esplora_semplice.LEGENDA,
        "sigla": svc.sigla_firma(s), "ha_affiancamento": svc.ha_affiancamento(s),
        "motivo_non_firma_approvatore": svc.motivo_non_firma_approvatore(a, s),
        "motivo_non_firma_persona": svc.motivo_non_firma_persona(a, s, su_carta=False),
        "motivo_non_firma_carta": svc.motivo_non_firma_persona(a, s, su_carta=True),
        "partecipanti": [{"p": p, "nome": persona["nomi"].get(p.legacy_anagrafica_id) or f"#{p.legacy_anagrafica_id}",
                          "sono_io": bool(a.legacy_id) and a.legacy_id == p.legacy_anagrafica_id} for p in s.partecipanti.all()],
        "motivo_non_chiude": svc.motivo_non_chiude(a, s), "puo_chiudere_negativa": s.aperta and a.gestione,
        "eventi": list(s.eventi.all()), "corsi": TrainingCourse.objects.filter(is_active=True).only("pk", "codice", "titolo").order_by("titolo"),
        "modi": Riga.MODO_CHOICES, "verifiche": Riga.VERIFICA_CHOICES, "livelli": esplora_semplice.LEGENDA,
        "oggi": timezone.localdate(), "edizioni": svc.edizioni_persona(s.richiesta.legacy_anagrafica_id),
    })


def _esegui(request, s, azione, messaggio: str, *, log: str, notifica: str = ""):
    url = reverse("anagrafica:sessione", args=[s.pk])
    try:
        s = azione()
    except svc.SessioneNonValida as exc:
        messages.error(request, str(exc))
        return redirect(url)
    log_action(request, log, MODULE, {"sessione": s.codice, "stato": s.stato}, oggetto=s)
    if notifica:
        persona = s.richiesta.legacy_anagrafica_id
        _notifica({persona, _capo(persona)} - {rq.attore(request).legacy_id}, f"{s.codice}: {notifica}", url)
    messages.success(request, messaggio)
    return redirect(url)


@login_required
@require_POST
def apri(request, richiesta_pk: int):
    a = rq.attore(request)
    richiesta = get_object_or_404(R, pk=richiesta_pk)
    if not rq.puo_vedere(a, richiesta):
        raise Http404
    try:
        s = svc.apri(a, richiesta)
    except svc.SessioneNonValida as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:richiesta", pk=richiesta.pk)
    log_action(request, "sessione_formativa_aperta", MODULE, {"sessione": s.codice, "richiesta": richiesta.codice},
               oggetto=s)
    url = reverse("anagrafica:sessione", args=[s.pk])
    persona = richiesta.legacy_anagrafica_id
    _notifica({persona, _capo(persona)} - {a.legacy_id}, f"{s.codice}: sessione formativa aperta.", url)
    messages.success(request, f"Sessione {s.codice} aperta.")
    return redirect(url)


@login_required
@require_POST
def valuta(request, riga_pk: int):
    riga = get_object_or_404(Riga.objects.select_related("sessione"), pk=riga_pk)
    a, s = _sessione_visibile(request, riga.sessione_id)
    p = request.POST

    mancanti_prima = len(svc.righe_mancanti(s))

    def fai():
        svc.valuta(a, riga, modalita=p.get("modalita") or "", livello=p.get("livello") or "", nota=p.get("nota") or "",
                   conferma_cambio=p.get("conferma_cambio") == "1", descrizione=p.get("descrizione") or "",
                   data_verifica=p.get("data_verifica"), tutor_nome=p.get("tutor_nome") or "", dal=p.get("dal"),
                   al=p.get("al"), ore=p.get("ore"), registro=_file(request, "registro_mod040"),
                   corso_id=_int(p.get("corso")), docente_ente=p.get("docente_ente") or "",
                   data_corso=p.get("data_corso"), verifica=p.get("verifica") or "",
                   edizione_id=_int(p.get("edizione")))
        dopo = S.objects.get(pk=s.pk)
        _avvisi_valutazione(a, dopo, mancanti_prima)
        return dopo

    return _esegui(request, s, fai, f"«{riga.competenza_nome}» salvata.", log="sessione_formativa_valutazione")


def _avvisi_valutazione(a, s, mancanti_prima: int) -> None:
    """Avanzamento: il responsabile lo sa se valuta un altro; chi firma lo sa quando tutto è valutato."""
    url = reverse("anagrafica:sessione", args=[s.pk])
    persona = s.richiesta.legacy_anagrafica_id
    capo = _capo(persona)
    if capo and capo != a.legacy_id:
        _notifica({capo}, f"{s.codice}: una competenza è stata valutata.", url)
    if mancanti_prima and not svc.righe_mancanti(s):
        sigla = svc.sigla_firma(s)
        _notifica(rq.titolari(sigla) - {a.legacy_id}, f"{s.codice}: tutte le competenze valutate, tocca a {sigla} firmare.", url)


@login_required
@require_POST
def firma_approvatore(request, pk: int):
    a, s = _sessione_visibile(request, pk)
    return _esegui(request, s, lambda: svc.firma_approvatore(a, s, visto_mod040=request.POST.get("visto_mod040") == "1"),
                   f"Sessione {s.codice} firmata.", log="sessione_formativa_firma_approvatore",
                   notifica="firmata da chi ha approvato: tocca alla persona firmare.")


@login_required
@require_POST
def firma_persona(request, pk: int):
    a, s = _sessione_visibile(request, pk)
    su_carta = request.POST.get("modo") == "carta"
    return _esegui(request, s, lambda: svc.firma_persona(a, s, su_carta=su_carta, data_firma=request.POST.get("data_firma"),
                                                         file=_file(request, "foglio") if su_carta else None,
                                                         persona_id=_int(request.POST.get("persona"))),
                   "Firma della persona registrata.", log="sessione_formativa_firma_persona")


@login_required
@require_POST
def chiudi(request, pk: int):
    a, s = _sessione_visibile(request, pk)
    if request.POST.get("esito") == "negativa":
        return _esegui(request, s, lambda: svc.chiudi_negativa(a, s, motivo=request.POST.get("motivo") or ""),
                       f"Sessione {s.codice} chiusa come negativa.", log="sessione_formativa_chiusa_negativa",
                       notifica="sessione chiusa con esito negativo.")
    return _esegui(request, s, lambda: svc.chiudi(a, s), f"Sessione {s.codice} chiusa: livelli aggiornati.",
                   log="sessione_formativa_chiusa", notifica="sessione chiusa, livelli aggiornati.")


@login_required
def scarica(request, pk: int, cosa: str, riga_pk: int | None = None):
    _, s = _sessione_visibile(request, pk)
    if cosa == "firma" and riga_pk:
        f = get_object_or_404(s.partecipanti, pk=riga_pk).firma_file
    elif cosa == "mod040" and riga_pk:
        f = get_object_or_404(Riga, pk=riga_pk, sessione=s).registro_mod040
    else:
        raise Http404
    if not f:
        raise Http404
    return FileResponse(f.open("rb"), as_attachment=True, filename=f.name.rsplit("/", 1)[-1])


@login_required
def pdf(request, pk: int):
    from django.http import HttpResponse

    from .services import sessione_pdf

    _, s = _sessione_visibile(request, pk)
    persona = svc.righe([s])[0]["persona"]
    risposta = HttpResponse(sessione_pdf.build_pdf(s, persona), content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="{s.codice}.pdf"'
    log_action(request, "sessione_formativa_pdf", MODULE, {"sessione": s.codice}, oggetto=s)
    return risposta


def _riga_persona(legacy_id: int) -> dict:
    from .services import struttura_vista
    from .services.reparto_canonico import build_area_canonica_map

    area = build_area_canonica_map([legacy_id]).get(legacy_id)
    return {"id": legacy_id, "nome": struttura_vista._nomi([legacy_id]).get(legacy_id) or f"#{legacy_id}",
            "area": area.nome if area else "",
            "centro": area.centro_di_costo.nome if area is not None and area.centro_di_costo_id else ""}


@login_required
def storico_pdf(request, legacy_id: int):
    """Storico di formazione e competenze: lo vedono la persona, il suo responsabile, la Qualità e HR."""
    from django.http import HttpResponse

    from .services import persona_semplice, storico_persona_pdf

    a = rq.attore(request)
    if not (a.gestione or legacy_id in a.team or (a.legacy_id and a.legacy_id == legacy_id)):
        raise Http404
    persona = persona_semplice.costruisci(_riga_persona(legacy_id))
    risposta = HttpResponse(storico_persona_pdf.build_pdf(legacy_id, persona), content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="storico_competenze_{legacy_id}.pdf"'
    log_action(request, "storico_competenze_pdf", MODULE, {"persona": legacy_id})
    return risposta


@login_required
@require_POST
def matricole(request):
    """Numero di partenza e accensione dei contatori: solo chi amministra l'anagrafica."""
    from .models_sessioni import ContatoreMatricola
    from .views import _helpers

    if not _helpers._is_anagrafica_admin(request):
        raise Http404
    a = rq.attore(request)
    cambiati = []
    for c in ContatoreMatricola.objects.select_for_update().all():
        ultimo = _int(request.POST.get(f"ultimo_{c.pk}"))
        cifre = _int(request.POST.get(f"cifre_{c.pk}"))
        attivo = request.POST.get(f"attivo_{c.pk}") == "1"
        prima = (c.ultimo, c.cifre, c.attivo)
        if ultimo is not None and ultimo >= 0:
            c.ultimo = ultimo
        if cifre is not None and 1 <= cifre <= 8:
            c.cifre = cifre
        c.attivo = attivo
        if (c.ultimo, c.cifre, c.attivo) != prima:
            c.aggiornato_da = (a.nome or "")[:160]
            c.save()
            cambiati.append({"prefisso": c.prefisso, "prima": list(prima), "dopo": [c.ultimo, c.cifre, c.attivo]})
    if cambiati:
        log_action(request, "matricole_contatori", MODULE, {"cambiati": cambiati})
        messages.success(request, "Contatori delle matricole salvati.")
    return redirect(f"{reverse('anagrafica:sessioni')}#matricole")
