"""Wizard guidati del modulo Contatori: per ora «Nuovo dispositivo SNMP»."""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action

from .permessi import richiede_gestione
from .wizard import WizardDispositivo


def _iniziali_da_query(get):
    """Precompilazione dai link di Discovery: solo valori grezzi, validati dai form dei passi."""
    dati = {}
    if get.get("nome"):
        dati["tipo"] = {"nome": get["nome"][:100]}
    rete = {k: get[k][:253] for k in ("host", "porta", "versione") if get.get(k)}
    if rete:
        dati["rete"] = {"porta": "161", "versione": "v2c", **rete}
    if (get.get("community_id") or "").isdigit():
        dati["credenziali"] = {"community_salvata": get["community_id"]}
    return dati


@richiede_gestione
def wizard_dispositivo_avvia(request):
    wid = WizardDispositivo.avvia(request, _iniziali_da_query(request.GET))
    return redirect("contatori:snmp_wizard_dispositivo", wid=wid)


def _fine(request, url):
    if request.headers.get("HX-Request"):
        risposta = HttpResponse(status=204)
        risposta["HX-Redirect"] = url
        return risposta
    return redirect(url)


@richiede_gestione
def wizard_dispositivo(request, wid):
    try:
        wiz = WizardDispositivo(request, wid)
    except KeyError:
        messages.warning(request, "Questo wizard è scaduto o è già stato completato: ricomincia da qui.")
        return _fine(request, reverse("contatori:snmp_wizard_dispositivo_avvia"))

    form, avviso, dispositivo = None, "", None
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
                if wiz.indice == WizardDispositivo.TEST and not wiz.test_valido():
                    avviso = ("Esegui il test di connessione e fai in modo che riesca: "
                              "senza test superato il dispositivo non si può completare.")
                else:
                    wiz.vai(wiz.indice + 1)
                    form = None
        elif azione == "test" and wiz.indice == WizardDispositivo.TEST:
            if not wiz.esegui_test():
                avviso = "Rete o credenziali non sono più valide: correggi i passi precedenti."
            esito, parametri = wiz.extra("test") or {}, wiz.parametri()
            # Traccia ogni sonda verso la rete (mai il segreto): chi, dove, con quale credenziale.
            cred = wiz.form_valido("credenziali")
            salvata = cred.cleaned_data.get("community_salvata") if cred else None
            log_action(request, "snmp_wizard_test", "contatori", dettaglio={
                "host": parametri[0] if parametri else "", "porta": parametri[1] if parametri else None,
                "versione": parametri[2] if parametri else "",
                "credenziale": salvata.pk if salvata else ("nuova" if cred and cred._segreto_inline else "globale"),
                "esito": "ok" if esito.get("ok") else (esito.get("errore") or {}).get("codice", "")})
        elif azione == "leggi" and wiz.passo.chiave == "mappatura":
            wiz.leggi_mappatura()
        elif azione == "bozza":
            if wiz.form_valido("tipo") is None or wiz.form_valido("rete") is None:
                avviso = "Per salvare una bozza completa almeno «Tipo e modello» e «Rete»."
            elif form is None or form.is_valid():
                dispositivo, avviso = _salva(wiz, bozza=True)
            if dispositivo is not None:
                log_action(request, "snmp_dispositivo_bozza", "contatori", oggetto=dispositivo,
                           dettaglio={"host": dispositivo.host, "verificato": dispositivo.verificato})
                if dispositivo.verificato:
                    messages.success(request, f"«{dispositivo.nome}» salvato: il test di connessione era già riuscito.")
                else:
                    messages.warning(request, f"«{dispositivo.nome}» salvato come bozza NON verificata: "
                                              "verrà verificato alla prima lettura SNMP riuscita.")
                return _fine(request, reverse("contatori:snmp_dispositivo", args=[dispositivo.pk]))
        elif azione == "conferma":
            incompleto = wiz.primo_passo_incompleto()
            if incompleto is not None:
                avviso = f"Il passo «{wiz.passi[incompleto].titolo}» non è più valido: correggilo."
                wiz.vai(incompleto)
            elif not wiz.test_valido():
                avviso = "Rete o credenziali sono cambiate dopo il test: ripetilo."
                wiz.vai(WizardDispositivo.TEST)
            else:
                dispositivo, avviso = _salva(wiz, bozza=False)
            if dispositivo is not None:
                log_action(request, "snmp_dispositivo_creato_wizard", "contatori", oggetto=dispositivo,
                           dettaglio={"host": dispositivo.host, "profilo": str(dispositivo.profilo_snmp or "")})
                messages.success(request, f"Dispositivo «{dispositivo.nome}» creato e verificato.")
                return _fine(request, reverse("contatori:snmp_dispositivo", args=[dispositivo.pk]))

    # Nessun passo oltre il test senza test superato; nessun passo dopo uno non valido.
    incompleto = wiz.primo_passo_incompleto(fino_a=wiz.indice)
    if incompleto is not None:
        wiz.vai(incompleto)
        form = None
    elif wiz.indice > WizardDispositivo.TEST and not wiz.test_valido():
        wiz.vai(WizardDispositivo.TEST)
        form = None
    passo = wiz.passo
    if form is None and passo.form_class is not None:
        form = wiz.form(passo.chiave)

    contesto = {"wiz": wiz, "passo": passo, "form": form, "avviso": avviso, "test": wiz.extra("test"),
                "profilo_diverso": wiz.profilo_diverso_dal_rilevato() if passo.chiave == "test" else None,
                "test_valido": wiz.test_valido(), "profilo": wiz.profilo(),
                "mappatura": wiz.extra("mappatura")}
    if passo.chiave == "associazione" and form is not None and not form.is_bound and not form.initial.get("asset"):
        asset, motivo = wiz.proposta_asset()
        if asset is not None:
            form.initial["asset"] = asset.pk
            contesto["proposta_asset"] = f"Proposto {asset.asset_tag} trovato tramite {motivo}: verifica."
    if passo.chiave == "riepilogo":
        contesto["riepilogo"] = _riepilogo(wiz)
    return render(request, "contatori/snmp_wizard.html", contesto)


def _salva(wiz, *, bozza):
    """(dispositivo, avviso): un altro wizard puo' aver registrato lo stesso host nel frattempo."""
    from django.db import IntegrityError
    try:
        return wiz.salva(bozza=bozza), ""
    except IntegrityError:
        wiz.vai(1)
        return None, "Nel frattempo questo indirizzo è stato registrato da un altro dispositivo: cambialo."


def _riepilogo(wiz):
    tipo, rete = wiz.form_valido("tipo"), wiz.form_valido("rete")
    cred, assoc = wiz.form_valido("credenziali"), wiz.form_valido("associazione")
    righe = []
    if tipo:
        categorie = dict(tipo.fields["categoria"].choices)
        righe += [("Nome", tipo.cleaned_data["nome"]), ("Tipo", categorie.get(tipo.cleaned_data["categoria"]))]
    if rete:
        righe += [("Indirizzo", f"{rete.cleaned_data['host']}:{rete.cleaned_data['porta']}"),
                  ("Versione", rete.cleaned_data["versione"])]
    if cred:
        if cred._segreto_inline:
            origine = "Nuova credenziale, salvata cifrata nel catalogo"
        elif cred.cleaned_data.get("community_salvata"):
            origine = f"Catalogo: {cred.cleaned_data['community_salvata'].nome}"
        else:
            origine = "Community della configurazione globale"
        righe.append(("Credenziali", origine))
    profilo = wiz.profilo()
    righe.append(("Profilo", str(profilo) if profilo else "Nessuno: solo identità e uptime"))
    if assoc:
        asset = assoc.cleaned_data.get("asset")
        righe += [("Asset", f"{asset.asset_tag} · {asset.name}" if asset else "Non collegato"),
                  ("Reparto / posizione", assoc.cleaned_data.get("posizione") or "—")]
    return righe
