"""Explicit provenance of report columns and links to the existing source editors."""
from django.urls import NoReverseMatch, reverse

# In column order. Kept explicit: no introspection of private model fields or arbitrary URLs.
COLUMN_SOURCES = {
    "inventario-it": ["Asset: tag inventario", "Asset: nome", "Asset: tipo dispositivo", "Asset: marca + modello", "Asset: numero di serie", "Asset: reparto assegnazione, altrimenti reparto", "Asset: assegnatario", "Asset: stato"],
    "licenze-software": ["Licenza: prodotto + edizione", "Licenza: fornitore", "Licenza: categoria", "Licenza: assegnatario, altrimenti reparto", "Licenza: posti usati / totali", "Licenza: data rinnovo", "Licenza: scadenza", "Licenza: rinnovo automatico", "Calcolato da scadenza (o rinnovo) e posti utilizzati"],
    "revisione-accessi": ["Utente portale: username", "Utente portale: nome completo", "Profilo: ruolo legacy", "Utente: superuser o staff", "Utente: ultimo login", "Configurazione 2FA: attiva e confermata", "ACL: conteggio dinieghi aperti per utente legacy", "Calcolato da cessazione, ultimo login, privilegi e 2FA"],
    "sicurezza-it": ["Security Center: CVE acquisita", "Vulnerabilita: prodotto", "Vulnerabilita: gravita", "Vulnerabilita: CVSS", "Vulnerabilita: dispositivi esposti", "Vulnerabilita: prima rilevazione", "Giorni dalla prima rilevazione a oggi", "Vulnerabilita: stato"],
    "dichiarazione-applicabilita": ["Controllo ISO 27001: codice", "Controllo: titolo", "Voce SoA approvata: livello", "Voce SoA: azione", "Voce SoA: responsabile", "Voce SoA: scadenza", "Calcolato da azione aperta e scadenza"],
    "registro-nc-ofi": ["Registro OFI: numero", "Registro OFI: tipo", "ISO 9001 + norme selezionate nella voce", "Registro OFI: riferimento norma", "Registro OFI: processo", "Registro OFI: opportunita (testo abbreviato)", "Registro OFI: priorita", "Registro OFI: fase", "Registro OFI: apertura", "Registro OFI: chiusura richiesta", "Registro OFI: chiusura effettiva", "Giorni da apertura a chiusura oppure oggi", "Owner processo, altrimenti proprietario"],
    "albo-fornitori": ["Fornitore: ragione sociale", "Fornitore: categoria", "Ultima valutazione: data", "Ultima valutazione: qualita", "Ultima valutazione: puntualita", "Ultima valutazione: comunicazione", "Media dei tre voti, un decimale", "Numero valutazioni nel periodo", "Numero documenti di tipo certificazione", "Calcolato da media e anzianita della valutazione"],
    "verifiche-periodiche": ["Verifica periodica: nome", "Verifica: fornitore associato", "Verifica: frequenza in mesi", "Verifica: ultima data", "Verifica: prossima data", "Asset collegati: primi 6 tag o nomi", "Calcolato da prossima data e preavviso 30 giorni"],
    "presa-visione": ["Documento: codice", "Documento: titolo", "Revisione corrente: codice", "Data efficacia, altrimenti data revisione", "Assegnazioni non annullate", "Assegnazioni confermate", "Confermate / assegnate", "Assegnazioni oltre scadenza o con stato in ritardo"],
    "manutenzione": ["Categoria asset, altrimenti Senza categoria", "Occorrenze non annullate con scadenza nel periodo", "Occorrenze completate", "Completate entro la scadenza", "Non completate e scadenza passata", "Nei tempi / (eseguite + scadute)", "Minuti fermo delle completate / 60"],
    "audit-interni": ["Audit: numero", "Audit: data inizio", "Audit: tipo", "Audit: processi (testo abbreviato)", "Audit: norme", "Lead auditor: nome", "Audit: stato", "Checklist: conteggio OFI", "Checklist: conteggio NC", "Rapporto: data valutazione RDD"],
    "competenze": ["Anagrafica legacy: nominativo", "Anagrafica legacy: reparto", "Scadenzario formazione oppure qualifica", "Corso oppure tipo qualifica", "Requisito formazione o qualifica: scadenza", "Stato formazione oppure calcolato da scadenza qualifica"],
    "processi-speciali": ["Processo qualificato: nome", "Processo: regime", "Processo: cliente", "Processo: scadenza o validita illimitata", "Anagrafica dipendente o nominativo esterno", "Abilitazione: ruoli attivi", "Prima scadenza certificazioni individuali attive", "Calcolato da cessazione, certificazione e scadenza processo"],
    "efficacia-formazione": ["Anagrafica legacy: nominativo", "Anagrafica legacy: reparto", "Record formativo: titolo snapshot o corso", "Record: data completamento", "Efficacia: attesa dal", "Efficacia: valutata il", "Efficacia: esito o Da valutare", "Efficacia: azione (testo abbreviato)"],
    "eventi-sicurezza": ["Segnalazione: data", "Segnalazione: tipo scheda", "Segnalazione: tipo evento", "Segnalazione: reparto", "Segnalazione: causa (testo abbreviato)", "Presenza del primo perche nell'analisi", "Misure tecniche (testo abbreviato) oppure No", "Segnalazione: approvazione RLS", "Data chiusura RSPP oppure Aperta", "Giorni da segnalazione a chiusura"],
    "dpi": ["Richiesta DPI: numero", "Richiesta: nome richiedente", "Richiesta: reparto", "Richiesta: categoria", "Richiesta: tipo DPI", "Consegna: data", "Consegna: firma ricevuta", "Consegna: scadenza stimata", "Calcolato da scadenza e firma"],
    "scadenziario-legale": ["Ambito monitorato", "Riferimento associato all'ambito", "Conteggio scadute o mancanti nel modulo sorgente", "Conteggio scadenze entro 30 giorni", "Conteggio elementi monitorati", "(Totale - scadute) / totale"],
}


def record_links(obj):
    model = obj._meta.label_lower
    routes = {
        "assets.asset": ("assets:asset_edit", [obj.pk]),
        "assets.softwarelicense": ("assets:software_license_list", []),
        "assets.periodicverification": ("assets:periodic_verifications", []),
        "anagrafica.fornitore": ("fornitori:fornitore_detail", [obj.pk]),
        "gestione_specifiche.registroofi": ("registro_ofi:dettaglio", [obj.pk]),
        "sistema_gestione.audit": ("sistema_gestione:audit_dettaglio", [obj.pk]),
    }
    route = routes.get(model)
    if model == "procedure_refresh.procedurerevision":
        route = ("procedure_refresh:revision_edit", [obj.document_id, obj.pk])
    elif model in {"anagrafica.trainingdeadline", "anagrafica.dipendentequalifica", "anagrafica.trainingefficacia"}:
        route = ("anagrafica:dipendente_detail", [obj.legacy_anagrafica_id])
    elif model == "anagrafica.processoqualificato":
        route = ("anagrafica:mpq_processo_detail", [obj.pk])
    elif model == "anagrafica.abilitazioneprocesso":
        route = ("anagrafica:mpq_processo_detail", [obj.processo_id])
    elif model == "dpi.consegnadpi":
        route = ("dpi:gestione_detail", [obj.richiesta_id])
    if model == "sistema_gestione.soavoce":
        route = ("sistema_gestione:soa_revisione", [obj.revisione.numero])
    if not route:
        return []
    try:
        url = reverse(route[0], args=route[1])
        if model in {"assets.softwarelicense", "assets.periodicverification"}:
            url += f"?edit={obj.pk}"
        return [("Apri sorgente", url)]
    except NoReverseMatch:
        return []


def allowed_links(request, items):
    from core.middleware import acl_allows_path

    allowed = []
    for label, url in items:
        try:
            if acl_allows_path(url.split("?", 1)[0], django_user=request.user,
                               legacy_user=getattr(request, "legacy_user", None), request=request):
                allowed.append((label, url))
        except Exception:
            continue
    return allowed
