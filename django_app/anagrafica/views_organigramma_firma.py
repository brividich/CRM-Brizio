"""Organigramma ufficiale: firma su portale (MT CN 08 §7.2.1).

Con la firma accesa «Pubblica» diventa «Invia in firma»: la bozza si congela,
chi invia firma la Redazione, RDD firma l'Approvazione e solo allora nasce la
revisione. Regole, immagini e conferma dell'identità: ``timbri/firme.py``.

Inviare e ritirare: chi disegna (binding della pubblicazione). Firmare e
respingere: chi deve firmare la casella in attesa, controllato qui dentro
(binding della consultazione, così RDD non deve poter disegnare).
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action
from timbri import firme
from timbri.models import CasellaFirma, DocumentoFirma

from .services import organigramma_firma
from .services import organigramma_ufficiale as svc
from .views import _helpers
from .views_organigramma_ufficiale import _org, _puo_disegnare

CHIAVE = organigramma_firma.CHIAVE


def puo_impostare_firme(request) -> bool:
    return bool(request.user.is_superuser or _helpers.is_legacy_admin(_helpers.get_legacy_user(request.user)))


def firma_attiva() -> bool:
    return firme.impostazione(CHIAVE)["attiva"]


def doc_in_firma(org):
    return firme.in_firma(CHIAVE, org.pk)


def _coinvolto(user, doc) -> bool:
    return doc.creato_da_id == user.pk or any(firme.puo_firmare_casella(user, c) for c in doc.caselle.all())


def _url_firma(org) -> str:
    return reverse("anagrafica:organigramma_ufficiale_firma", args=[org.pk])


def _dopo_chiusura(org):
    if org.revisione_in_vigore():
        return redirect("anagrafica:organigramma_ufficiale_vedi", pk=org.pk)
    return redirect("anagrafica:organigramma_ufficiale")


def caselle_vista(doc, user) -> list[dict]:
    corrente = firme.casella_corrente(doc) if doc.stato == DocumentoFirma.STATO_IN_FIRMA else None
    out = []
    for c in doc.caselle.all():
        if c.mittente:
            chi = firme.nome_utente(doc.creato_da) if doc.creato_da else ""
        else:
            chi = ", ".join(firme.nome_utente(u) for u in firme.utenti_del_ruolo(c.ruolo)[:4])
        out.append({
            "c": c, "chi": chi,
            "corrente": corrente is not None and c.pk == corrente.pk,
            "url_firma": reverse("anagrafica:organigramma_ufficiale_firma_immagine", args=[c.pk, "firma"]) if c.immagine_firma else "",
            "url_timbro": reverse("anagrafica:organigramma_ufficiale_firma_immagine", args=[c.pk, "timbro"]) if c.immagine_timbro else "",
        })
    return out


def firme_della_revisione(rev, user) -> dict | None:
    """Firme di una revisione per vedi e stampa (``None`` = pubblicata senza firma su portale)."""
    doc = firme.firmato_per_esito(CHIAVE, rev.pk) if rev else None
    if doc is None:
        return None
    return {"doc": doc, "caselle": caselle_vista(doc, user)}


def contesto_invio(request, org) -> dict:
    """Per il dialogo «Invia in firma» della tela."""
    imp = firme.impostazione(CHIAVE)
    if not imp["attiva"]:
        return {"attiva": False}
    caselle = []
    for c in imp["caselle"]:
        ruolo = None if c["mittente"] else firme._ruolo_della_casella(c)
        persone = [] if c["mittente"] else [firme.nome_utente(u) for u in firme.utenti_del_ruolo(ruolo)]
        caselle.append({**c, "ruolo_obj": ruolo, "persone": persone,
                        "problema": (not c["mittente"]) and (ruolo is None or not persone)})
    prima = caselle[0] if caselle else None
    opzioni = []
    if prima and prima["mittente"]:
        finta = CasellaFirma(varianti=",".join(prima["varianti"]))
        opzioni = firme.opzioni(request.user, finta)
    return {"attiva": True, "caselle": caselle, "firma_subito": bool(prima and prima["mittente"]),
            "opzioni": opzioni, "usa_totp": firme.usa_totp(request.user)}


def _apri(campo):
    """Immagine archiviata; se il file non c'è più è un 404, non un errore del server."""
    try:
        return campo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404() from None


@login_required
@require_POST
def organigramma_ufficiale_invia(request, pk: int):
    """Congela la bozza, la manda in firma e firma subito la casella di chi invia."""
    org = _org(pk)
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di inviare in firma gli organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    if org.bozza is None or not svc.normalizza(org.bozza)["nodi"]:
        messages.error(request, "Il disegno è vuoto: aggiungi almeno un riquadro prima di inviarlo in firma.")
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    try:
        data_emissione = date.fromisoformat((request.POST.get("data_emissione") or "").strip())
    except ValueError:
        data_emissione = date.today()
    in_vigore = org.revisione_in_vigore()
    numero = (in_vigore.numero + 1) if in_vigore else 1
    nota = (request.POST.get("nota") or "").strip()[:2000]
    try:
        with transaction.atomic():
            doc = firme.invia(
                CHIAVE, oggetto_id=org.pk, titolo=f"{org.nome} · Rev.{numero}", numero=numero,
                contenuto=organigramma_firma.contenuto(org, nota=nota, data_emissione=data_emissione),
                nota=nota, user=request.user,
            )
            prima = firme.casella_corrente(doc)
            if prima is not None and prima.mittente:
                doc = firme.firma(request, doc, user=request.user, scelta=request.POST.get("scelta") or "",
                                  segreto=request.POST.get("segreto") or "",
                                  dichiarazione=request.POST.get("dichiarazione") == "1")
    except firme.FirmaNegata as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    log_action(request, "organigramma_ufficiale_inviato_in_firma", "anagrafica",
               {"nome": org.nome, "revisione": numero, "impronta": doc.impronta}, oggetto=org)
    if doc.stato == DocumentoFirma.STATO_FIRMATO:
        messages.success(request, f"Firmata e pubblicata la Rev.{numero} di «{org.nome}».")
        return redirect("anagrafica:organigramma_ufficiale_vedi", pk=org.pk)
    firme.avvisa_prossimi(doc, _url_firma(org))
    messages.success(request, f"Rev.{numero} inviata in firma: chi deve firmare ha ricevuto la notifica.")
    return redirect("anagrafica:organigramma_ufficiale_firma", pk=org.pk)


def _azione(request, org, doc, gestisce: bool):
    azione = request.POST.get("azione")
    if azione == "firma":
        doc = firme.firma(request, doc, user=request.user, scelta=request.POST.get("scelta") or "",
                          segreto=request.POST.get("segreto") or "",
                          dichiarazione=request.POST.get("dichiarazione") == "1")
        log_action(request, "organigramma_ufficiale_firmato", "anagrafica",
                   {"nome": org.nome, "revisione": doc.numero_revisione, "impronta": doc.impronta}, oggetto=org)
        if doc.stato == DocumentoFirma.STATO_FIRMATO:
            if doc.creato_da and doc.creato_da_id != request.user.pk:
                firme.notifica(doc.creato_da, "firma_completata", f"Firmato e pubblicato: {doc.titolo}",
                               reverse("anagrafica:organigramma_ufficiale_vedi", args=[org.pk]))
            messages.success(request, f"Firmato: la Rev.{doc.numero_revisione} è in vigore.")
            return redirect("anagrafica:organigramma_ufficiale_vedi", pk=org.pk)
        firme.avvisa_prossimi(doc, _url_firma(org))
        messages.success(request, "Firma apposta: il documento passa alla casella successiva.")
        return redirect("anagrafica:organigramma_ufficiale_firma", pk=org.pk)
    if azione == "respingi":
        doc = firme.respingi(doc, user=request.user, motivo=request.POST.get("motivo") or "")
        log_action(request, "organigramma_ufficiale_firma_respinta", "anagrafica",
                   {"nome": org.nome, "revisione": doc.numero_revisione, "motivo": doc.motivo}, oggetto=org)
        if doc.creato_da:
            firme.notifica(doc.creato_da, "firma_respinta", f"Respinto: {doc.titolo} – {doc.motivo}",
                           reverse("anagrafica:organigramma_ufficiale_disegna", args=[org.pk]))
        messages.success(request, "Documento respinto: chi l'ha inviato può correggere la bozza e rimandarla.")
        return _dopo_chiusura(org)
    if azione == "ritira":
        if not (gestisce or doc.creato_da_id == request.user.pk):
            raise firme.FirmaNegata("Può ritirare solo chi l'ha inviato o chi disegna gli organigrammi.")
        firme.ritira(doc, user=request.user, motivo=request.POST.get("motivo") or "")
        log_action(request, "organigramma_ufficiale_firma_ritirata", "anagrafica",
                   {"nome": org.nome, "revisione": doc.numero_revisione}, oggetto=org)
        messages.success(request, "Richiesta di firma ritirata: la bozza è di nuovo modificabile.")
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    raise firme.FirmaNegata("Azione non riconosciuta.")


@login_required
def organigramma_ufficiale_firma(request, pk: int):
    """Documento in firma: anteprima congelata, caselle, Firma / Respingi / Ritira."""
    org = _org(pk)
    doc = doc_in_firma(org)
    gestisce = _puo_disegnare(request)
    if doc is None:
        messages.info(request, "Non c'è nessun documento in firma per questo organigramma.")
        return _dopo_chiusura(org)
    if request.method == "POST":
        try:
            return _azione(request, org, doc, gestisce)
        except firme.FirmaNegata as exc:
            messages.error(request, str(exc))
            return redirect("anagrafica:organigramma_ufficiale_firma", pk=org.pk)
    if not (gestisce or _coinvolto(request.user, doc)):
        raise Http404()
    in_vigore = org.revisione_in_vigore()
    dati = (doc.contenuto or {}).get("dati")
    corrente = firme.casella_corrente(doc)
    mia = corrente is not None and firme.puo_firmare_casella(request.user, corrente)
    return render(request, "anagrafica/pages/organigramma_ufficiale_firma.html", {
        "org": org, "doc": doc, "in_vigore": in_vigore,
        "pacchetto": svc.pacchetto(dati),
        "righe": svc.riepilogo(in_vigore.dati if in_vigore else None, dati),
        "caselle": caselle_vista(doc, request.user),
        "corrente": corrente, "mia": mia,
        "puo_respingere": mia and not corrente.mittente,
        "opzioni": firme.opzioni(request.user, corrente) if mia else [],
        "usa_totp": firme.usa_totp(request.user),
        "puo_ritirare": gestisce or doc.creato_da_id == request.user.pk,
        "data_emissione": (doc.contenuto or {}).get("data_emissione") or "",
        "mittente_nome": firme.nome_utente(doc.creato_da) if doc.creato_da else "—",
    })


@login_required
@require_GET
def organigramma_ufficiale_firma_immagine(request, casella_id: int, variante: str):
    """Immagine copiata nella casella: documento firmato = chi vede l'organigramma; in firma = chi è coinvolto."""
    casella = get_object_or_404(CasellaFirma.objects.select_related("documento"), pk=casella_id,
                                documento__tipo=CHIAVE)
    if not firme.puo_vedere_immagine(request.user, casella, vede_documento=True, gestisce=_puo_disegnare(request)):
        raise Http404()
    campo = {"firma": casella.immagine_firma, "timbro": casella.immagine_timbro}.get(variante)
    if not campo:
        raise Http404()
    risposta = FileResponse(_apri(campo), content_type="image/png")
    risposta["Cache-Control"] = "private, max-age=300"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta


@login_required
@require_GET
def organigramma_ufficiale_mia_immagine(request, image_id: int):
    """Anteprima di una delle proprie immagini del Registro timbri, per scegliere cosa mettere nella casella."""
    img = next((i for i in firme.immagini_proprie(request.user).values() if i.pk == image_id), None)
    if img is None:
        raise Http404()
    risposta = FileResponse(_apri(img.image), content_type="image/png")
    risposta["Cache-Control"] = "private, no-store"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta


@login_required
@require_POST
def organigramma_ufficiale_firme_impostazioni(request):
    if not puo_impostare_firme(request):
        messages.error(request, "Solo gli amministratori del portale cambiano le firme richieste.")
        return redirect("anagrafica:organigramma_ufficiale")
    caselle = []
    for i in range(firme.MAX_CASELLE):
        etichetta = request.POST.get(f"c{i}_etichetta") or ""
        chi = request.POST.get(f"c{i}_chi") or ""
        if not etichetta.strip() or not chi:
            continue
        caselle.append({
            "etichetta": etichetta, "mittente": chi == "mittente",
            "ruolo": chi if chi.isdigit() else None,
            "varianti": request.POST.getlist(f"c{i}_varianti"),
        })
    try:
        imp = firme.salva_impostazione(CHIAVE, attiva=request.POST.get("attiva") == "1", caselle=caselle,
                                       user=request.user)
    except firme.FirmaNegata as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:organigramma_ufficiale")
    log_action(request, "organigramma_ufficiale_firme_impostate", "anagrafica", imp)
    messages.success(request, "Firme richieste aggiornate." if imp["attiva"] else
                     "Firma su portale spenta: gli organigrammi si pubblicano senza firme.")
    return redirect("anagrafica:organigramma_ufficiale")


def impostazioni_vista() -> dict:
    """Impostazioni con il ruolo risolto, per il dialogo «Firme richieste» dell'elenco."""
    from anagrafica.models import RuoloOperativo

    imp = firme.impostazione(CHIAVE)
    righe = []
    for c in imp["caselle"]:
        ruolo = None if c["mittente"] else firme._ruolo_della_casella(c)
        righe.append({**c, "chi": "mittente" if c["mittente"] else (str(ruolo.pk) if ruolo else "")})
    while len(righe) < firme.MAX_CASELLE:
        righe.append({"etichetta": "", "chi": "", "varianti": ["FIRMA"]})
    return {
        "attiva": imp["attiva"], "righe": righe,
        "ruoli": list(RuoloOperativo.objects.filter(is_active=True).order_by("nome").values("pk", "nome", "sigla")),
    }
