"""Acquisizione dei referti di sorveglianza sanitaria — viste.

Gemello dell'acquisizione dei fogli firme, con una differenza che ne cambia
l'ergonomia. Là il QR identifica il documento con certezza, e la pagina serve
soprattutto a diagnosticare i fallimenti; qui il dipendente va **riconosciuto**,
quindi l'esito normale di un'acquisizione è una proposta e non una registrazione.
Per questo la pagina principale non è il registro ma la **coda di revisione**.

Il permesso è quello delle visite mediche (``AnagraficaVisiteMedichePermission``,
default ADMIN), e non uno nuovo: confermare un abbinamento *è* registrare una
visita, sugli stessi dati sanitari (art. 9 GDPR). Un secondo permesso per la
stessa cosa sarebbe solo un secondo posto dove sbagliare a configurare.

Importato da ``urls.py`` come modulo dedicato (``from . import views_sorveglianza``).
"""
from __future__ import annotations

import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

logger = logging.getLogger(__name__)


def _puo(request) -> bool:
    """Chi può registrare una visita medica può lavorare sui referti."""
    from .views import _can_view_visite_mediche

    return _can_view_visite_mediche(request)


def _nega(request):
    messages.error(request, "Non hai i permessi per gestire i referti sanitari.")
    return redirect("anagrafica:visite_mediche_dashboard")


def _audit(request, azione: str, dettaglio: dict | None = None) -> None:
    log_action(request, azione, "anagrafica", dettaglio or {})


def _nomi_per_legacy_ids(ids) -> dict[int, str]:
    """Nominativi dei dipendenti proposti, da mostrare accanto alla proposta.

    Una proposta che dice solo «id 7921» costringerebbe chi revisiona ad aprire
    un'altra pagina per ogni riga: il nome è ciò che rende la coda scorribile.
    """
    voluti = {int(i) for i in ids if i}
    if not voluti:
        return {}
    try:
        from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

        ensure_anagrafica_schema()
        fuori = {}
        for row in fetch_anagrafica_rows(deduplicate=True):
            legacy_id = int(row.get("id") or 0)
            if legacy_id in voluti:
                fuori[legacy_id] = " ".join(p for p in (
                    str(row.get("cognome") or "").strip(),
                    str(row.get("nome") or "").strip(),
                ) if p)
        return fuori
    except Exception:
        logger.exception("Referti: nominativi non risolti")
        return {}


@login_required
def referti_coda(request):
    """I referti letti che aspettano una decisione.

    Ogni riga mostra cosa si è letto, chi si propone e **perché** non ci si è
    fidati da soli. Il motivo conta quanto la proposta: è ciò che permette di
    decidere in fretta invece di riaprire ogni scansione.
    """
    if not _puo(request):
        return _nega(request)

    from .models_sorveglianza import RefertoIntakeRiga
    from .services.referti_ocr import disponibile as ocr_disponibile

    righe = list(
        RefertoIntakeRiga.objects
        .filter(esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE)
        .select_related("creato_da")[:200]
    )

    nomi = _nomi_per_legacy_ids([r.legacy_anagrafica_id_proposto for r in righe])
    for riga in righe:
        riga.nome_proposto = nomi.get(riga.legacy_anagrafica_id_proposto or 0, "")

    conteggi = {
        "da_rivedere": RefertoIntakeRiga.objects.filter(
            esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE).count(),
        "registrati": RefertoIntakeRiga.objects.filter(
            esito=RefertoIntakeRiga.ESITO_OK).count(),
    }

    return render(request, "anagrafica/pages/referti_coda.html", {
        "righe": righe,
        "conteggi": conteggi,
        "ocr_attivo": ocr_disponibile(),
    })


@login_required
@require_POST
def referti_carica(request):
    """Caricamento multiplo dal browser.

    Convive con la cartella di rete e non la sostituisce: la cartella serve a chi
    scansiona in blocco, questa a chi ha tre file sul desktop e non ha ragione di
    imparare dove sta la share.
    """
    if not _puo(request):
        return _nega(request)

    from .services.referti_intake import elabora_contenuto

    caricati = request.FILES.getlist("referti")
    if not caricati:
        messages.error(request, "Nessun file selezionato.")
        return redirect("anagrafica:referti_coda")

    totale = registrati = in_coda = problemi = 0
    for f in caricati:
        try:
            contenuto = f.read()
        except Exception:
            logger.exception("Referti: file caricato non leggibile (%s)", f.name)
            problemi += 1
            continue
        for riga in elabora_contenuto(contenuto, f.name, origine="WEB", utente=request.user):
            totale += 1
            if riga.esito == riga.ESITO_OK:
                registrati += 1
            elif riga.esito == riga.ESITO_DA_RIVEDERE:
                in_coda += 1
            else:
                problemi += 1

    _audit(request, "referti_caricati", {
        "file": len(caricati), "certificati": totale,
        "registrati": registrati, "in_coda": in_coda,
    })

    pezzi = [f"{totale} certificati letti"]
    if registrati:
        pezzi.append(f"{registrati} registrati")
    if in_coda:
        pezzi.append(f"{in_coda} da rivedere")
    if problemi:
        pezzi.append(f"{problemi} con problemi")
    messages.info(request, " · ".join(pezzi))
    return redirect("anagrafica:referti_coda")


@login_required
@require_POST
def referti_conferma(request, riga_id: int):
    """Conferma l'abbinamento e registra le visite del protocollo.

    Il dipendente si può correggere: la proposta resta una proposta, e chi
    revisiona ha la scansione davanti. Quando lo corregge, in audit finisce anche
    il fatto che il sistema aveva proposto altro — serve a capire, col tempo,
    quanto ci si possa fidare del riconoscimento.
    """
    if not _puo(request):
        return _nega(request)

    from .models_sorveglianza import RefertoIntakeRiga
    from .services.referti_registrazione import ErroreRegistrazione, registra

    riga = get_object_or_404(RefertoIntakeRiga, pk=riga_id)

    scelto = (request.POST.get("legacy_id") or "").strip()
    legacy_id = None
    if scelto:
        try:
            legacy_id = int(scelto)
        except (TypeError, ValueError):
            messages.error(request, "Dipendente non valido.")
            return redirect("anagrafica:referti_coda")

    proposto = riga.legacy_anagrafica_id_proposto
    corretto_a_mano = bool(legacy_id and legacy_id != proposto)

    try:
        create = registra(riga, utente=request.user, legacy_id=legacy_id)
    except ErroreRegistrazione as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:referti_coda")
    except Exception:
        logger.exception("Referti: registrazione fallita (riga %s)", riga.pk)
        messages.error(request, "Registrazione fallita: riprova o segnala il problema.")
        return redirect("anagrafica:referti_coda")

    _audit(request, "referto_confermato", {
        "riga_id": riga.pk,
        "legacy_id": riga.legacy_anagrafica_id_proposto,
        "proposto_dal_sistema": proposto,
        "corretto_a_mano": corretto_a_mano,
        "punteggio": riga.punteggio,
        "conferma_data_nascita": riga.data_nascita_conferma,
        "visite_create": len(create),
    })
    quale = riga.letto_nominativo or "questo dipendente"
    messages.success(request, f"{len(create)} visite registrate dal referto di {quale}.")
    return redirect("anagrafica:referti_coda")


@login_required
@require_POST
def referti_scarta(request, riga_id: int):
    """Toglie dalla coda un referto che non va registrato.

    Non cancella niente: il file resta in archivio e la riga nel registro. Uno
    scarto è una decisione, e le decisioni si conservano.
    """
    if not _puo(request):
        return _nega(request)

    from .models_sorveglianza import RefertoIntakeRiga

    riga = get_object_or_404(RefertoIntakeRiga, pk=riga_id)
    motivo = (request.POST.get("motivo") or "").strip()

    riga.esito = RefertoIntakeRiga.ESITO_SCARTATO
    riga.messaggio = motivo or "Scartato manualmente."
    riga.confermato_da = request.user
    riga.confermato_il = timezone.now()
    riga.save(update_fields=["esito", "messaggio", "confermato_da", "confermato_il"])

    _audit(request, "referto_scartato", {"riga_id": riga.pk, "motivo": motivo})
    messages.info(request, "Referto tolto dalla coda. Resta archiviato nel registro.")
    return redirect("anagrafica:referti_coda")


@login_required
def referti_registro(request):
    """Tutto quello che è passato dall'acquisizione, riuscito o no.

    Esiste per il caso in cui la lettura fallisce: il messaggio a schermo dice
    *che* è andata male, qui c'è il file vero da riaprire e guardare.
    """
    if not _puo(request):
        return _nega(request)

    from .models_sorveglianza import RefertoIntakeRiga

    righe = RefertoIntakeRiga.objects.select_related("creato_da", "confermato_da")

    esito = (request.GET.get("esito") or "").strip().upper()
    if esito in {e for e, _ in RefertoIntakeRiga.ESITO_CHOICES}:
        righe = righe.filter(esito=esito)

    cerca = (request.GET.get("q") or "").strip()
    if cerca:
        righe = righe.filter(
            Q(nome_file__icontains=cerca) | Q(letto_nominativo__icontains=cerca)
        )

    righe = list(righe[:300])
    nomi = _nomi_per_legacy_ids([r.legacy_anagrafica_id_proposto for r in righe])
    for riga in righe:
        riga.nome_proposto = nomi.get(riga.legacy_anagrafica_id_proposto or 0, "")

    # Chiave, etichetta e conteggio già appaiati: il template non sa indicizzare
    # un dizionario con una variabile, e un filtro apposta non vale una riga qui.
    filtri = [
        (chiave, etichetta, RefertoIntakeRiga.objects.filter(esito=chiave).count())
        for chiave, etichetta in RefertoIntakeRiga.ESITO_CHOICES
    ]

    return render(request, "anagrafica/pages/referti_registro.html", {
        "righe": righe,
        "esito": esito,
        "cerca": cerca,
        "totale": RefertoIntakeRiga.objects.count(),
        "filtri": filtri,
    })


@login_required
def referti_impostazioni(request):
    """Cartella, parametri di lettura, soglie e tabelle di traduzione.

    Le due tabelle di alias in fondo non sono un dettaglio di configurazione:
    sono il punto in cui un certificato scritto in modo mai visto smette di
    essere un problema di sviluppo e diventa una riga da inserire.
    """
    if not _puo(request):
        return _nega(request)

    from .forms import (
        AliasEsameProtocolloForm,
        AliasEsitoIdoneitaForm,
        RefertoIntakeConfigForm,
    )
    from .models_sorveglianza import (
        AliasEsameProtocollo,
        AliasEsitoIdoneita,
        RefertoIntakeConfig,
    )
    from .services.referti_ocr import disponibile as ocr_disponibile
    from .services.referti_ocr import percorso_tesseract

    config = RefertoIntakeConfig.load()
    form = RefertoIntakeConfigForm(instance=config)
    form_esame = AliasEsameProtocolloForm()
    form_esito = AliasEsitoIdoneitaForm()

    if request.method == "POST":
        azione = (request.POST.get("azione") or "salva").strip()

        if azione == "prova":
            from .services.referti_intake import elabora_cartella

            esito = elabora_cartella(config)
            _audit(request, "referti_intake_prova", {
                "cartella": config.cartella, "riepilogo": esito.get("riepilogo", ""),
            })
            messages.info(request, f"Passaggio eseguito: {esito.get('riepilogo', '')}")
            return redirect("anagrafica:referti_impostazioni")

        if azione == "alias_esame":
            form_esame = AliasEsameProtocolloForm(request.POST)
            if form_esame.is_valid():
                form_esame.save()
                messages.success(request, "Alias esame aggiunto.")
                return redirect("anagrafica:referti_impostazioni")
            messages.error(request, "Controlla i campi dell'alias esame.")

        elif azione == "alias_esito":
            form_esito = AliasEsitoIdoneitaForm(request.POST)
            if form_esito.is_valid():
                form_esito.save()
                messages.success(request, "Alias giudizio aggiunto.")
                return redirect("anagrafica:referti_impostazioni")
            messages.error(request, "Controlla i campi dell'alias giudizio.")

        elif azione == "alias_esame_elimina":
            AliasEsameProtocollo.objects.filter(pk=request.POST.get("alias_id") or 0).delete()
            messages.info(request, "Alias esame rimosso.")
            return redirect("anagrafica:referti_impostazioni")

        elif azione == "alias_esito_elimina":
            AliasEsitoIdoneita.objects.filter(pk=request.POST.get("alias_id") or 0).delete()
            messages.info(request, "Alias giudizio rimosso.")
            return redirect("anagrafica:referti_impostazioni")

        else:
            form = RefertoIntakeConfigForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                _audit(request, "referti_intake_config", {
                    "attiva": config.attiva, "cartella": config.cartella,
                    "conferma_automatica": config.conferma_automatica,
                    "ocr_dpi": config.ocr_dpi, "ocr_psm": config.ocr_psm,
                })
                messages.success(request, "Impostazioni dell'acquisizione salvate.")
                return redirect("anagrafica:referti_impostazioni")
            messages.error(request, "Controlla i campi segnalati.")

    # Lo stato della cartella si guarda adesso, non si ricorda: una share può
    # essere sparita dall'ultimo salvataggio.
    stato_cartella = "non configurata"
    if (config.cartella or "").strip():
        try:
            stato_cartella = "raggiungibile" if os.path.isdir(config.cartella) else "non raggiungibile"
        except OSError:
            stato_cartella = "non raggiungibile"

    # Una lettera di unità *può* essere un disco locale del server, quindi non si
    # rifiuta; ma è più spesso una mappatura dell'utente collegato, che un servizio
    # non vede — e il sintomo sarebbe una cartella eternamente vuota.
    cartella = (config.cartella or "").strip()
    avviso_lettera_unita = len(cartella) > 2 and cartella[1] == ":"

    return render(request, "anagrafica/pages/referti_impostazioni.html", {
        "form": form,
        "config": config,
        "stato_cartella": stato_cartella,
        "avviso_lettera_unita": avviso_lettera_unita,
        "ocr_attivo": ocr_disponibile(),
        "ocr_percorso": percorso_tesseract(),
        "form_esame": form_esame,
        "form_esito": form_esito,
        "alias_esami": AliasEsameProtocollo.objects.select_related("tipo"),
        "alias_esiti": AliasEsitoIdoneita.objects.all(),
    })


@login_required
def referto_scarica(request, riga_id: int):
    """Riscarica la scansione archiviata di un referto.

    L'archivio è privato e cifrato a riposo: non si apre da Esplora risorse. Si
    passa di qui, dove ci sono permessi e traccia, perché è un dato sanitario.
    """
    if not _puo(request):
        return _nega(request)

    from .models_sorveglianza import RefertoIntakeRiga
    from .services.archivio_scansioni import apri_archiviata

    riga = get_object_or_404(RefertoIntakeRiga, pk=riga_id)
    f = apri_archiviata(riga.percorso)
    if f is None:
        messages.error(request, "Il file archiviato non è più disponibile.")
        return redirect("anagrafica:referti_coda")

    _audit(request, "referto_archiviato_scaricato", {
        "riga_id": riga.pk, "percorso": riga.percorso, "nome_file": riga.nome_file,
    })
    return FileResponse(f, as_attachment=True, filename=riga.nome_file or "referto.pdf")
