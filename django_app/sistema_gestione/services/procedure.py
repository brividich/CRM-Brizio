"""Regole operative derivate dalle procedure interne, senza inferenze normative."""
from decimal import Decimal
import re
from django.core.exceptions import ValidationError
from django.utils import timezone
from ..models import Audit, Processo, CellaProgramma, AuditPreparazione


def copertura_annuale(programma):
    celle = list(CellaProgramma.objects.filter(riga__programma=programma).select_related("riga", "audit"))
    conclusi = Audit.objects.filter(stato=Audit.STATO_CHIUSO, data_inizio__year=programma.anno).prefetch_related("processi_catalogo")
    eseguiti = {p.pk for a in conclusi for p in a.processi_catalogo.all()}
    righe = []
    for p in Processo.objects.filter(attivo=True):
        applicabili = [c for c in celle if c.riga.processo_id == p.pk and (not c.audit_id or (c.audit.stato != Audit.STATO_ANNULLATO and c.audit.data_inizio.year == programma.anno))]
        mesi = sorted({c.mese for c in applicabili})
        scoperti = []
        for campo in ["punti_9100", "punti_45001", "punti_27001", "punti_pdr125"]:
            richiesti = {v.strip() for v in re.split(r"[,;\n]", getattr(p, campo)) if v.strip()}
            coperti = {v.strip() for c in applicabili for v in re.split(r"[,;\n]", getattr(c.riga, campo)) if v.strip()}
            scoperti.extend(campo.removeprefix("punti_") + ": " + v for v in sorted(richiesti-coperti))
        righe.append({"processo": p, "mesi": mesi, "scoperti": scoperti, "pianificato": bool(mesi) and not scoperti, "eseguito": p.pk in eseguiti})
    return righe


def verifica_copertura(programma):
    righe = copertura_annuale(programma)
    if not righe:
        raise ValidationError("Completa il catalogo processi prima di proporre il programma annuale (MT CN 12).")
    mancanti = [r["processo"].codice for r in righe if not r["pianificato"]]
    if mancanti:
        raise ValidationError("MT CN 12: mancano mesi o riferimenti del catalogo nel programma per i processi " + ", ".join(mancanti))


def problemi_preparazione(audit):
    try:
        p = audit.preparazione
    except AuditPreparazione.DoesNotExist:
        return ["Completa l'esame preparatorio previsto dalla MT CN 12."]
    if any(not getattr(p, f).strip() for f in ("audit_precedenti", "car_cliente", "documenti_registrazioni", "obiettivi_carenze")):
        return ["Completa tutti i riferimenti dell'esame preparatorio."]
    if audit.piano_approvato_direzione_il and p.verificato_il < audit.piano_approvato_direzione_il:
        return ["Riconferma la preparazione sul piano approvato."]
    return []


def risultato_kpi(k):
    if k.denominatore <= 0 or k.numeratore < 0:
        raise ValidationError("Numeratore non negativo e denominatore maggiore di zero obbligatori; un dato mancante non vale zero.")
    valore = k.numeratore / k.denominatore
    classe = ""
    if k.formula == "VENDOR":
        if k.numeratore > k.denominatore or k.pezzi_totali is None or k.pezzi_totali <= 0 or k.pezzi_nc is None or not 0 <= k.pezzi_nc <= k.pezzi_totali:
            raise ValidationError("Per VR servono consegne puntuali/totali e pezzi NC/totali coerenti.")
        valore = valore * Decimal("0.30") + (1 - k.pezzi_nc / k.pezzi_totali) * Decimal("0.70")
        classe = "Regolare" if valore >= Decimal("0.80") else "Monitoraggio" if valore >= Decimal("0.70") else "Attenzione"
    elif k.formula == "PERCENTUALE":
        valore *= 100
    return {"valore": valore, "classe": classe, "target_raggiunto": valore >= k.target if k.verso == "MIN" else valore <= k.target,
            "delta": valore-k.valore_precedente if k.confrontabile and k.valore_precedente is not None else None}


def problemi_chiusura_car(car, utente):
    problemi = []
    if not car.approvata_il:
        problemi.append("Approva prima l'analisi e l'azione correttiva.")
    if car.origine_esterna and not car.approvazione_esterna.strip():
        problemi.append("Indica il riferimento all'approvazione del cliente/ente richiedente.")
    if car.responsabile_id == utente.pk:
        problemi.append("La verifica deve essere effettuata da persona distinta dal responsabile dell'azione (MT CN 11).")
    if not all([car.causa.strip(), car.contenimento.strip(), car.azione.strip(), car.analizzata_il, car.evidenza_attuazione.strip(), car.evidenza_efficacia.strip()]):
        problemi.append("Completa causa, contenimento, azione, data analisi, attuazione e verifica di efficacia.")
    return problemi
