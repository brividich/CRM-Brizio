"""Automatismi deterministici: preparano dati e motivazioni, mai esiti o firme."""
from calendar import monthrange
from datetime import timedelta
from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone
from ..models import Audit, AuditEsito, ChecklistProcesso, ProcessoRevisione


def registra_revisione(processo, utente, motivo):
    processo.revisione += 1
    processo.save(update_fields=["revisione", "updated_at"])
    ProcessoRevisione.objects.create(processo=processo, numero=processo.revisione,
        dati=processo.snapshot(), motivo=motivo, autore=utente)


def proponi_domande(processo):
    """Solo bozze da verificare; nessuna deduzione di clausole normative."""
    campi = [
        ("SCOPO", "scopo", "Quali evidenze dimostrano che lo scopo del processo viene raggiunto?"),
        ("INPUT", "input", "Come vengono verificati e accettati gli ingressi del processo?"),
        ("OUTPUT", "output", "Come viene verificata la conformita dei risultati attesi?"),
        ("RISCHI", "rischi", "Come vengono gestiti i rischi identificati nella scheda processo?"),
        ("KPI", "indicatori", "Gli indicatori sono misurati e confrontati con gli obiettivi?"),
        ("DOC", "procedure", "Il campione esaminato segue i documenti e le revisioni applicabili?"),
    ]
    create = 0
    for norma, campo_norma in [("en9100", "punti_9100"), ("iso45001", "punti_45001"),
                              ("iso27001", "punti_27001"), ("pdr125", "punti_pdr125")]:
        punti = getattr(processo, campo_norma)
        if not punti.strip():
            continue
        for ordine, (codice, campo, domanda) in enumerate(campi, 1):
            criterio = getattr(processo, campo).strip()
            if not criterio:
                continue
            _, nuova = ChecklistProcesso.objects.get_or_create(processo=processo,
                codice=f"{norma.upper()}-{codice}", defaults={
                    "norma": norma, "punti": punti[:100], "domanda": domanda,
                    "criterio": criterio, "suggerimento": "Indica documento/revisione, campione, data e risultato osservato.",
                    "ordine": ordine * 10, "attiva": False,
                })
            create += nuova
    return create


def genera_checklist_processi(audit):
    """Usa le sole schede storicizzate nel piano. Non aggiorna risposte esistenti."""
    create = 0
    chiavi = {d["id"] for s in audit.processi_snapshot for d in s.get("checklist", []) if getattr(audit, d["norma"], False)}
    if audit.stato == Audit.STATO_PIANIFICATO:
        audit.esiti.filter(modello_processo__isnull=False, versione=0, esito="", evidenze="", allegati__isnull=True).exclude(modello_processo_id__in=chiavi).delete()
    for scheda in audit.processi_snapshot:
        for domanda in scheda.get("checklist", []):
            if not getattr(audit, domanda["norma"], False):
                continue
            valori = {
                "processo_id": scheda["id"], "strutturato": True,
                "testo_aggiuntivo": domanda["domanda"], "punti_aggiuntivi": domanda["punti"],
                "requisito_atteso": domanda["criterio"],
                "domanda_snapshot": {**domanda, "processo": f'{scheda["codice"]} - {scheda["nome"]}'},
            }
            esito, nuova = AuditEsito.objects.get_or_create(audit=audit, modello_processo_id=domanda["id"], defaults=valori)
            if not nuova and audit.stato == Audit.STATO_PIANIFICATO and esito.versione == 0 and not esito.esito and not esito.evidenze and not esito.allegati.exists():
                for campo, valore in valori.items():
                    setattr(esito, campo, valore)
                esito.save()
            create += nuova
    return create


def problemi_esito(esito):
    problemi = []
    if not esito.esito:
        problemi.append("Scegli un esito")
    if esito.esito and not esito.evidenze.strip():
        problemi.append("Motiva l'esclusione" if esito.esito == "NA" else "Descrivi il risultato osservato")
    if esito.strutturato and esito.esito and esito.esito != "NA":
        for campo, label in [("documento", "riferimento documento o registrazione"),
                             ("revisione_documento", "revisione/versione del documento (o non applicabile motivato)"),
                             ("campione", "campione esaminato"), ("data_verifica", "data della verifica")]:
            if not str(getattr(esito, campo) or "").strip():
                problemi.append("Indica " + label)
        if esito.esito in {"NC", "OFI"}:
            for campo, label in [("requisito_atteso", "requisito atteso"), ("scostamento", "scostamento/opportunita"),
                                 ("responsabile_azione", "responsabile dell'azione"), ("scadenza_azione", "scadenza dell'azione")]:
                if not getattr(esito, campo):
                    problemi.append("Indica " + label)
    return problemi


def testo_evidenza(esito):
    righe = []
    if esito.domanda_snapshot.get("processo"):
        righe.append("Processo: " + esito.domanda_snapshot["processo"])
    for campo, titolo in [("requisito_atteso", "Requisito atteso"), ("documento", "Documento/registrazione"),
                          ("revisione_documento", "Revisione"), ("campione", "Campione"),
                          ("data_verifica", "Data verifica"), ("evidenze", "Risultato / motivazione N/A"),
                          ("scostamento", "Scostamento / opportunita")]:
        valore = getattr(esito, campo)
        if valore:
            righe.append(f"{titolo}: {valore}")
    return "\n".join(righe)


def riepilogo_rapporto(audit):
    esiti = list(audit.esiti.select_related("ofi", "responsabile_azione").prefetch_related("allegati"))
    conteggi = {valore: sum(e.esito == valore for e in esiti) for valore in ["CONFORME", "NC", "OFI", "NA", ""]}
    righe = [f"Audit {audit.numero} del {audit.data_inizio:%d/%m/%Y}", f"Processi: {audit.processi}",
             f"Norme: {audit.norme_label}", f"Criteri: {audit.procedure_criteri}",
             f"Verifiche: {len(esiti)}; conformi: {conteggi['CONFORME']}; NC: {conteggi['NC']}; OFI: {conteggi['OFI']}; N/A: {conteggi['NA']}; da valutare: {conteggi['']}."]
    for esito in esiti:
        righe.append(f"\n{esito.punti} - {esito.testo}\nEsito: {esito.get_esito_display() or 'Da valutare'}\n{testo_evidenza(esito)}")
        if esito.ofi_id:
            righe.append(f"Registro MOD.174 n. {esito.ofi.numero}; responsabile: {esito.ofi.proprietario}; scadenza: {esito.ofi.data_richiesta or 'non definita'}.")
        for allegato in esito.allegati.all():
            righe.append(f"Allegato: {allegato.nome}; SHA-256: {allegato.sha256}")
    return "\n".join(righe)


def aggiungi_mesi(data, mesi):
    anno, mese = divmod(data.year * 12 + data.month - 1 + mesi, 12)
    anno = min(anno, 9999)
    mese += 1
    return data.replace(year=anno, month=mese, day=min(data.day, monthrange(anno, mese)[1]))


def priorita_processi(processi, oggi=None):
    """Punteggio operativo 0-100, versione 1. Non e una valutazione normativa del rischio."""
    oggi = oggi or timezone.localdate()
    risultati = []
    recenti = AuditEsito.objects.filter(esito="NC", audit__data_inizio__gte=oggi-timedelta(days=730), audit__data_inizio__lte=oggi).exclude(audit__stato=Audit.STATO_ANNULLATO).prefetch_related("verifiche_efficacia")
    processi = processi.prefetch_related(
        Prefetch("audit", queryset=Audit.objects.only("id", "stato", "data_inizio", "processi_snapshot"), to_attr="audit_priorita"),
        Prefetch("esiti_audit", queryset=recenti, to_attr="nc_priorita"),
    )
    for processo in processi:
        chiusi = sorted((a for a in processo.audit_priorita if a.stato == Audit.STATO_CHIUSO), key=lambda a: a.data_inizio, reverse=True)
        ultimo = chiusi[0].data_inizio if chiusi else None
        scadenza = aggiungi_mesi(ultimo, min(processo.frequenza_mesi, 12)) if ultimo else oggi
        score = processo.criticita * 10
        motivi = [f"Criticita dichiarata {processo.get_criticita_display()}: +{score}"]
        if not ultimo:
            score += 30
            motivi.append("Nessun audit chiuso collegato: +30")
        elif scadenza <= oggi:
            punti = min(30, 10 + (oggi - scadenza).days // 30 * 5)
            score += punti
            motivi.append(f"Verifica in scadenza/scaduta di {(oggi-scadenza).days} giorni: +{punti}")
        esiti = processo.nc_priorita
        nc = len(esiti)
        if nc:
            punti = min(30, nc * 10)
            score += punti
            motivi.append(f"{nc} NC attribuite al processo negli ultimi 24 mesi: +{punti}")
        non_efficaci = sum(1 for e in esiti
                          if e.verifiche_efficacia.all() and e.verifiche_efficacia.all()[0].risultato != "EFFICACE")
        if non_efficaci:
            score += 10
            motivi.append("Verifiche di efficacia ancora negative/in sospeso: +10")
        ultimo_audit = chiusi[0] if chiusi else None
        if ultimo_audit and any(s["id"] == processo.pk and s["revisione"] < processo.revisione for s in ultimo_audit.processi_snapshot):
            score += 10
            motivi.append("Scheda revisionata dopo l'ultima versione verificata: +10")
        score = min(100, score)
        risultati.append({"processo": processo, "punteggio": score, "motivi": motivi,
            "scadenza": scadenza, "data_proposta": oggi if scadenza <= oggi else min(scadenza, oggi+timedelta(days=30)) if score >= 60 else scadenza,
            "priorita": "Alta" if score >= 60 else "Media" if score >= 30 else "Bassa",
            "programmato": any(a.data_inizio >= oggi and a.stato not in [Audit.STATO_CHIUSO, Audit.STATO_ANNULLATO] for a in processo.audit_priorita)})
    return sorted(risultati, key=lambda r: (-r["punteggio"], r["scadenza"], r["processo"].codice))


def stato_efficacia(esito):
    ultimo = esito.verifiche_efficacia.first()
    if ultimo:
        return ultimo.get_risultato_display()
    if esito.ofi_id and esito.ofi.is_chiuso:
        return "Azione chiusa: efficacia da verificare"
    return "Azione da completare / efficacia da verificare"
