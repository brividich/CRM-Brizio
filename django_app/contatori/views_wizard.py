"""View unica dei wizard guidati del modulo Contatori (dispositivo, MFC, profilo, colonna, sonda)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action

from .permessi import richiede_gestione
from .wizard import wizard_per_tipo


def _classe(tipo):
    try:
        return wizard_per_tipo(tipo)
    except KeyError as e:
        raise Http404("Wizard inesistente") from e


@richiede_gestione
def wizard_avvia(request, tipo):
    cls = _classe(tipo)
    try:
        iniziali, ctx = cls.da_query(request.GET)
    except ValueError:
        messages.error(request, "Il wizard va aperto dalla pagina dell'oggetto a cui appartiene.")
        return redirect("contatori:snmp_centrale")
    wid = cls.avvia(request, iniziali, ctx)
    return redirect("contatori:wizard", tipo=tipo, wid=wid)


def _fine(request, url):
    if request.headers.get("HX-Request"):
        risposta = HttpResponse(status=204)
        risposta["HX-Redirect"] = url
        return risposta
    return redirect(url)


def _salva(wiz, *, bozza):
    """(oggetto, avviso). Concorrenza o vincoli violati: si resta nel wizard, niente 500."""
    try:
        return wiz.salva(bozza=bozza), ""
    except IntegrityError:
        incompleto = wiz.indice_ammesso()
        if incompleto is not None:  # il passo con il dato in conflitto, se si riconosce
            wiz.vai(incompleto)
        return None, ("Nel frattempo un altro utente ha registrato un oggetto con gli stessi dati "
                      "(indirizzo, matricola o OID): correggili.")
    except ValidationError as e:
        return None, "Dati non coerenti: " + " ".join(e.messages)
    except ValueError:  # un passo e' diventato non valido tra il controllo e il salvataggio
        return None, "Un passo non è più valido: ricontrolla i dati e riprova."


@richiede_gestione
def wizard(request, tipo, wid):
    cls = _classe(tipo)
    try:
        wiz = cls(request, wid)
    except KeyError:
        messages.warning(request, "Questo wizard è scaduto o è già stato completato: ricomincia da qui.")
        return _fine(request, reverse("contatori:snmp_centrale"))

    form, avviso, obj, bozza = None, "", None, False
    if request.method == "POST":
        azione, _, destinazione = request.POST.get("azione", "").partition(":")
        passo = wiz.passo
        if passo.form_class is not None and azione in ("avanti", "indietro", "bozza", "vai"):
            form = wiz.form(passo.chiave, data=request.POST)
            if form.is_valid():
                wiz.memorizza(passo.chiave, form)
            elif azione in ("indietro", "vai"):
                wiz.ricorda_bozza(passo.chiave, form)  # tornando indietro non bloccano ne' si perdono
                form = None
        if azione == "indietro":
            wiz.vai(wiz.indice - 1)
            form = None
        elif azione == "vai" and destinazione.isdigit():
            if int(destinazione) < wiz.indice:
                wiz.vai(int(destinazione))
            form = None
        elif azione == "avanti":
            if form is None or form.is_valid():
                avviso = wiz.blocco(passo.chiave)
                if not avviso:
                    wiz.vai(wiz.indice + 1)
                    form = None
        elif azione in wiz.azioni and wiz.azioni[azione][0] == passo.chiave:
            avviso = getattr(wiz, wiz.azioni[azione][1])()
            # Ogni sonda verso la rete resta tracciata (mai il segreto).
            if azione == "test":
                log_action(request, "snmp_wizard_test", "contatori", dettaglio=wiz.audit_test())
            elif azione == "prova":
                log_action(request, "snmp_wizard_prova_oid", "contatori", dettaglio=wiz.audit_prova())
        elif azione == "bozza" and wiz.consente_bozza:
            if wiz.form_valido("tipo") is None or wiz.form_valido("rete") is None:
                avviso = "Per salvare una bozza completa almeno «Tipo e modello» e «Rete»."
            elif form is None or form.is_valid():
                obj, avviso = _salva(wiz, bozza=True)
                bozza = True
        elif azione == "conferma":
            incompleto = wiz.indice_ammesso()
            if incompleto is not None:
                avviso = (wiz.blocco(wiz.passi[incompleto].chiave)
                          or f"Il passo «{wiz.passi[incompleto].titolo}» non è più valido: correggilo.")
                wiz.vai(incompleto)
            else:
                obj, avviso = _salva(wiz, bozza=False)
        if obj is not None:
            url, livello, testo, azione_audit, dettaglio = wiz.fine(obj, bozza=bozza)
            log_action(request, azione_audit, "contatori", oggetto=obj, dettaglio=dettaglio)
            getattr(messages, livello)(request, testo)
            return _fine(request, url)

    # Nessun passo dopo uno non valido o non superato (test, prova obbligatoria).
    incompleto = wiz.indice_ammesso(fino_a=wiz.indice)
    if incompleto is not None:
        wiz.vai(incompleto)
        form = None
    passo = wiz.passo
    if form is None and passo.form_class is not None:
        form = wiz.form(passo.chiave)

    contesto = {"wiz": wiz, "passo": passo, "form": form, "avviso": avviso, **wiz.contesto_passo(passo.chiave)}
    proponi = contesto.pop("proposta_asset", None)
    if proponi and form is not None and not form.is_bound and not form.initial.get("asset"):
        asset, motivo = proponi()
        if asset is not None:
            form.initial["asset"] = asset.pk
            contesto["proposta_asset"] = f"Proposto {asset.asset_tag} trovato tramite {motivo}: verifica."
    if passo.chiave == "riepilogo":
        contesto["riepilogo"] = wiz.riepilogo()
    return render(request, "contatori/snmp_wizard.html", contesto)
