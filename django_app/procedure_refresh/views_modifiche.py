"""CN-SGI: pagine delle modifiche ai documenti (redazione, verifica, approvazione, emissione).

- ``elenco``: le modifiche in lavorazione, con chi deve agire e da quanti giorni;
- ``nuova``: apertura (chi gestisce), anche da una segnalazione, dalla scheda o da «Da rivedere»;
- ``dettaglio``: bozze, confronto con la revisione in vigore, azioni del proprio ruolo, registro;
- ``bozza``: scarico della bozza (solo chi partecipa e chi gestisce);
- ``firme``: chi redige, verifica e approva di solito, per tipo di documento.

Accesso: chi gestisce vede tutto; gli altri solo le modifiche in cui hanno un ruolo.
La cartella SGI non viene mai scritta.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import esperienza as esp
from . import libreria as lib
from . import modifiche as mod
from .guida import con_guida
from .models import (
    ProcedureChangeRequest,
    ProcedureDocument,
    SgiFirmeTipo,
    SgiModifica,
    SgiModificaOrigine,
    SgiModificaStato,
    SgiScaffale,
)
from .views import _can_manage
from .views_libreria import _contesto_base, _solo_gestori


def _utenti():
    User = get_user_model()
    return list(User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
                .only("pk", "first_name", "last_name", "username"))


def _id_utente(raw, validi: set[int]):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() and int(raw) in validi else None


def _gestori_ids() -> list[int]:
    """Utenti da avvisare quando la modifica aspetta chi gestisce (destinatari del riepilogo)."""
    from .segnalazioni import destinatari_gestori

    try:
        from core.models import Profile

        legacy = destinatari_gestori()
        return list(Profile.objects.filter(legacy_user_id__in=legacy).values_list("user_id", flat=True)) if legacy else []
    except Exception:
        return []


def _ctx(request, **extra):
    vis = lib.Visibilita(request)
    return _contesto_base(request, vis, [], **extra)


@login_required
@con_guida
def elenco(request):
    gestore = _can_manage(request)
    stato = request.GET.get("stato") or ""
    if stato not in {s for s, _ in SgiModificaStato.choices}:
        stato = ""
    solo_mie = request.GET.get("mie") == "1"
    righe = mod.elenco(request.user, gestore, stato=stato, solo_mie=solo_mie)
    conta = {s: 0 for s, _ in SgiModificaStato.choices}
    for r in mod.elenco(request.user, gestore, solo_mie=solo_mie):
        conta[r.m.stato] = conta.get(r.m.stato, 0) + 1
    return render(request, "procedure_refresh/modifiche/elenco.html", _ctx(
        request,
        righe=righe, stato=stato, solo_mie=solo_mie, gestore=gestore,
        stati=[(s, l, conta.get(s, 0)) for s, l in SgiModificaStato.choices if s not in ("emessa", "annullata")],
        ruoli=mod.RUOLI, n_mie=sum(1 for r in righe if r.mia),
    ))


@login_required
@con_guida
def nuova(request):
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    utenti = _utenti()
    validi = {u.pk for u in utenti}
    doc = None
    raw_doc = request.POST.get("documento") or request.GET.get("doc") or ""
    codice = (request.POST.get("codice") or "").strip()
    if raw_doc.isdigit():
        doc = ProcedureDocument.objects.filter(pk=int(raw_doc), is_active=True).first()
    elif codice:
        doc = ProcedureDocument.objects.filter(code__iexact=codice, is_active=True).first()
    segn_ids = [int(x) for x in (request.POST.getlist("segnalazioni") or request.GET.getlist("segnalazione")) if str(x).isdigit()]
    segnalazioni = list(ProcedureChangeRequest.objects.filter(pk__in=segn_ids).select_related("document"))
    if doc is None and segnalazioni:
        doc = segnalazioni[0].document
    nuovo = request.POST.get("tipo") == "nuovo" or request.GET.get("tipo") == "nuovo"
    errori = []
    if request.method == "POST":
        dati = {
            "oggetto": (request.POST.get("oggetto") or "").strip()[:200],
            "motivo": (request.POST.get("motivo") or "").strip()[:4000],
            "origine": request.POST.get("origine") if request.POST.get("origine") in SgiModificaOrigine.values else SgiModificaOrigine.ALTRO,
            "riferimento": (request.POST.get("riferimento") or "").strip()[:200],
            "paragrafi": (request.POST.get("paragrafi") or "").strip()[:200],
            "revisione_prevista": (request.POST.get("revisione_prevista") or "").strip()[:20],
            "redattore_id": _id_utente(request.POST.get("redattore"), validi),
            "verificatore_id": _id_utente(request.POST.get("verificatore"), validi),
            "approvatore_id": _id_utente(request.POST.get("approvatore"), validi),
            "rilettura_automatica": request.POST.get("rilettura_automatica") == "1",
        }
        entro = request.POST.get("entro") or ""
        try:
            dati["entro"] = date.fromisoformat(entro) if entro else None
        except ValueError:
            dati["entro"] = None
        if nuovo:
            dati["nuovo_codice"] = (request.POST.get("nuovo_codice") or "").strip()[:50]
            dati["nuovo_titolo"] = (request.POST.get("nuovo_titolo") or "").strip()[:300]
            sc = request.POST.get("scaffale") or ""
            dati["scaffale"] = SgiScaffale.objects.filter(pk=int(sc)).first() if sc.isdigit() else None
            if not dati["nuovo_codice"] or not dati["nuovo_titolo"]:
                errori.append("Per un documento nuovo servono codice e titolo.")
            elif ProcedureDocument.objects.filter(code__iexact=dati["nuovo_codice"]).exists():
                errori.append(f"Il codice {dati['nuovo_codice']} esiste già: scegli il documento esistente.")
            doc = None
        elif doc is None:
            errori.append("Scegli il documento da modificare.")
        if not dati["oggetto"]:
            errori.append("Scrivi in breve cosa si modifica.")
        if not dati["motivo"]:
            errori.append("Scrivi perché.")
        if not dati["redattore_id"]:
            errori.append("Scegli chi redige.")
        if not errori:
            m = mod.apri(documento=doc, dati=dati, user=request.user, segnalazioni=segnalazioni)
            log_action(request, "crea", "procedure_refresh", {
                "message": "Modifica CN-SGI aperta", "modifica_id": m.pk, "code": m.codice,
            })
            messages.success(request, f"Modifica di {m.codice} aperta: {mod.nome(m.redattore)} può caricare la bozza.")
            return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
        for e in errori:
            messages.error(request, e)
    proposte = mod.firme_per(doc) if doc is not None else mod.firme_per(None)
    rev = doc.current_revision() if doc is not None else None
    aperta = mod.in_lavorazione_per(doc) if doc is not None else None
    origine = request.GET.get("origine") or ("segnalazione" if segnalazioni else "")
    return render(request, "procedure_refresh/modifiche/nuova.html", _ctx(
        request,
        doc=doc, rev=rev, nuovo=nuovo, aperta=aperta,
        segnalazioni=segnalazioni,
        altre_segnalazioni=(list(ProcedureChangeRequest.objects.filter(document=doc, status__in=["aperta", "in_carico"])
                                 .exclude(pk__in=[s.pk for s in segnalazioni]).order_by("-created_at")[:20])
                            if doc is not None else []),
        utenti=utenti, proposte=proposte, origini=SgiModificaOrigine.choices,
        origine=origine if origine in SgiModificaOrigine.values else "",
        prossima=mod.prossima_revisione(rev),
        documenti=list(ProcedureDocument.objects.filter(is_active=True).order_by("code").values("code", "title")[:3000]),
        scaffali=list(SgiScaffale.objects.filter(attivo=True).order_by("ordine", "nome")),
        prossimi_codici=mod.prossimi_codici() if nuovo else [],
        ruoli_form=[
            {"campo": c, "etichetta": mod.RUOLI[c],
             "scelto": (_id_utente(request.POST.get(c), validi) if request.method == "POST" else proposte.get(c))}
            for c in ("redattore", "verificatore", "approvatore")
        ],
        post=request.POST if request.method == "POST" else {},
    ))


def _modifica(request, pk):
    gestore = _can_manage(request)
    m = get_object_or_404(SgiModifica.objects.select_related(
        "documento", "redattore", "verificatore", "approvatore", "creata_da", "revisione_base", "revisione_emessa"), pk=pk)
    if not mod.puo_vedere(m, request.user, gestore):
        raise Http404("Modifica non disponibile.")
    return m, gestore, mod.ruoli_di(m, request.user, gestore)


@login_required
@con_guida
def dettaglio(request, pk: int):
    m, gestore, ruoli = _modifica(request, pk)
    bozze = list(m.bozze.select_related("caricata_da").order_by("-numero"))
    ultima = bozze[0] if bozze else None
    rev = m.documento.current_revision() if m.documento_id else None
    passi, attivo = [], True
    indice = {s: i for i, (s, _l, _r) in enumerate(mod.PASSI)}
    pos = indice.get(m.stato, -1)
    for i, (s, etichetta, ruolo) in enumerate(mod.PASSI):
        chi = getattr(m, ruolo, None) if ruolo in ("redattore", "verificatore", "approvatore") else None
        passi.append({"etichetta": etichetta, "chi": chi, "fatto": pos > i or m.stato == "emessa", "ora": pos == i and m.stato != "emessa"})
    ruolo_ora, chi_ora = mod.chi_deve_agire(m)
    revisioni_emissione = []
    if "emessa" in mod.azioni_possibili(m, ruoli):
        doc = m.documento
        if doc is None and m.nuovo_codice:
            doc = ProcedureDocument.objects.filter(code__iexact=m.nuovo_codice).first()
        if doc is not None:
            revisioni_emissione = [r for r in doc.revisions.order_by("-revision_date", "-pk") if r.pk != m.revisione_base_id][:10]
    utenti = _utenti() if "persone" in mod.azioni_possibili(m, ruoli) else []
    return render(request, "procedure_refresh/modifiche/dettaglio.html", _ctx(
        request,
        m=m, bozze=bozze, ultima=ultima, rev=rev, passi=passi,
        ruolo_ora=ruolo_ora, chi_ora=chi_ora, ruoli=ruoli, ruoli_label=mod.RUOLI,
        azioni=mod.azioni_possibili(m, ruoli),
        cambiamenti=mod.confronto(m, ultima),
        passaggi=list(m.passaggi.select_related("bozza").order_by("quando", "pk")),
        azioni_label=mod.AZIONI,
        segnalazioni=list(m.segnalazioni.select_related("created_by").order_by("created_at")),
        revisioni_emissione=revisioni_emissione,
        utenti=utenti,
        persone_form=[(c, getattr(m, f"{c}_id")) for c in ("redattore", "verificatore", "approvatore")],
        giorni=(timezone.now() - m.stato_dal).days,
        stesso_redattore_verificatore=bool(m.redattore_id and m.redattore_id in (m.verificatore_id, m.approvatore_id)),
    ))


@login_required
@require_POST
def azione(request, pk: int):
    m, gestore, ruoli = _modifica(request, pk)
    cosa = request.POST.get("azione") or ""
    nota = (request.POST.get("nota") or "")[:4000]
    revisione = None
    if cosa == "emessa":
        raw = request.POST.get("revisione") or ""
        if raw.isdigit():
            from .models import ProcedureRevision

            revisione = ProcedureRevision.objects.filter(pk=int(raw)).select_related("document").first()
            if revisione is not None and m.documento_id and revisione.document_id != m.documento_id:
                revisione = None
    if cosa == "approvata" and request.POST.get("conferma") != "1":
        messages.error(request, "Spunta la conferma per firmare l'approvazione.")
        return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
    try:
        esito = mod.esegui(m, cosa, request.user, ruoli, nota=nota, revisione=revisione, gestori=_gestori_ids())
    except mod.Rifiuto as exc:
        messages.error(request, str(exc))
        return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
    log_action(request, "modifica", "procedure_refresh", {
        "message": f"Modifica CN-SGI: {mod.AZIONI.get(cosa, cosa)}", "modifica_id": m.pk, "code": m.codice, "stato": m.stato,
    })
    messages.success(request, esito)
    return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)


@login_required
@require_POST
def carica(request, pk: int):
    m, gestore, ruoli = _modifica(request, pk)
    file = request.FILES.get("file")
    if file is None:
        messages.error(request, "Scegli il file della bozza.")
        return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
    try:
        b = mod.carica_bozza(m, file, request.user, ruoli, request.POST.get("sintesi") or "")
    except mod.Rifiuto as exc:
        messages.error(request, str(exc))
        return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
    log_action(request, "carica", "procedure_refresh", {
        "message": "Bozza CN-SGI caricata", "modifica_id": m.pk, "bozza": b.numero, "sha256": b.impronta,
    })
    messages.success(request, f"Bozza {b.numero} caricata." + ("" if b.testo else " Il testo non è leggibile: il confronto con la revisione in vigore non è disponibile."))
    return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)


@login_required
@require_POST
def persone(request, pk: int):
    m, gestore, ruoli = _modifica(request, pk)
    if "persone" not in mod.azioni_possibili(m, ruoli):
        messages.error(request, "Solo chi gestisce CN-SGI cambia le persone.")
        return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)
    validi = {u.pk for u in _utenti()}
    cambi, nuovi = [], []
    for campo in ("redattore", "verificatore", "approvatore"):
        nuovo = _id_utente(request.POST.get(campo), validi)
        if campo == "redattore" and nuovo is None:
            continue
        if getattr(m, f"{campo}_id") != nuovo:
            setattr(m, f"{campo}_id", nuovo)
            cambi.append(f"{mod.RUOLI[campo]}: {mod.nome(get_user_model().objects.filter(pk=nuovo).first()) or 'nessuno'}")
            if nuovo:
                nuovi.append((campo, nuovo))
    if cambi:
        m.save(update_fields=["redattore", "verificatore", "approvatore", "aggiornata_il"])
        mod.registra(m, "persone", request.user, ruolo="gestore", nota="; ".join(cambi), stato_da=m.stato)
        ruolo_ora, _chi = mod.chi_deve_agire(m)
        for campo, uid in nuovi:
            if campo == ruolo_ora:
                mod.avvisa([uid], f"Tocca a te su {m.codice} · {m.oggetto} ({mod.RUOLI[campo].lower()}).", mod.url_di(m))
        messages.success(request, "Persone aggiornate.")
    return redirect("procedure_refresh:modifica_dettaglio", pk=m.pk)


@login_required
def bozza(request, pk: int):
    from .models import SgiBozza

    b = get_object_or_404(SgiBozza.objects.select_related("modifica"), pk=pk)
    m, gestore, ruoli = _modifica(request, b.modifica_id)
    try:
        fh = b.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("File della bozza non trovato.")
    log_action(request, "scarica", "procedure_refresh", {
        "message": "Bozza CN-SGI scaricata", "modifica_id": m.pk, "bozza": b.numero,
    })
    resp = FileResponse(fh, as_attachment=True, filename=b.nome_file)
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@con_guida
def firme(request):
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    utenti = _utenti()
    validi = {u.pk for u in utenti}
    righe = {r.tipo: r for r in SgiFirmeTipo.objects.all()}
    if request.method == "POST":
        for tipo, _label in esp.TIPI:
            valori = {c: _id_utente(request.POST.get(f"{tipo}_{c}"), validi) for c in ("redattore", "verificatore", "approvatore")}
            riga = righe.get(tipo)
            if riga is None and not any(valori.values()):
                continue
            riga = riga or SgiFirmeTipo(tipo=tipo)
            for c, v in valori.items():
                setattr(riga, f"{c}_id", v)
            riga.save()
        log_action(request, "modifica", "procedure_refresh", {"message": "Firme CN-SGI per tipo aggiornate"})
        messages.success(request, "Firme per tipo di documento salvate.")
        return redirect("procedure_refresh:modifiche_firme")
    tipi = [{"tipo": t, "label": l, "riga": righe.get(t)} for t, l in esp.TIPI]
    return render(request, "procedure_refresh/modifiche/firme.html", _ctx(request, tipi=tipi, utenti=utenti))
