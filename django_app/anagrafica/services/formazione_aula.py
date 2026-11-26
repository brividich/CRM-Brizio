"""Sessioni in aula: presenze in un tocco, firma e test dal telefono, chiusura in un passo, efficacia.

Analisi del 25/11/2026 sui dati di produzione: le funzioni d'aula c'erano tutte ma
si usavano a metà (92 edizioni finite mai chiuse, 11 firme su 5.834 presenze, 0
valutazioni di efficacia, 0 approvazioni MOD.040). Qui le stesse cose con meno
passaggi; nessuna email ai partecipanti.

Riferimenti: MT CN 06 §9.2 (registrazione), §9.3 (approvazione MOD.040), §9.5 (efficacia).
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from ..models_formazione import (
    TrainingEfficacia,
    TrainingEnrollment,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingSession,
)

logger = logging.getLogger(__name__)

STATI_APERTI = ("ISCRITTO", "IN_CORSO")
STATI_FINALI = ("COMPLETATO", "NON_IDONEO", "ASSENTE", "RITIRATO")
MARGINE_MINUTI = 30          # il QR vale da mezz'ora prima a mezz'ora dopo la lezione
USCITA_DOPO_MINUTI = 30      # una seconda firma prima di 30' dall'ingresso non è un'uscita
SOGLIA_PRESENZA_PREDEFINITA = 90


class AulaError(Exception):
    """Messaggio da mostrare così com'è."""


# ─────────────────────────────────────────────────────────────────────────────
# Token e lezione del giorno
# ─────────────────────────────────────────────────────────────────────────────

def token(sessione: TrainingSession) -> str:
    if not sessione.token_aula:
        sessione.token_aula = secrets.token_urlsafe(24)
        TrainingSession.objects.filter(pk=sessione.pk).update(token_aula=sessione.token_aula)
    return sessione.token_aula


def sessione_da_token(tok: str) -> TrainingSession | None:
    if not tok or len(tok) < 20:
        return None
    return (TrainingSession.objects.select_related("corso").filter(token_aula=tok)
            .exclude(stato="ANNULLATA").first())


def _dt(data, ora) -> datetime:
    return timezone.make_aware(datetime.combine(data, ora))


def lezione_aperta(sessione, adesso=None) -> TrainingLesson | None:
    """La lezione di oggi il cui orario (± 30') comprende adesso."""
    adesso = timezone.localtime(adesso or timezone.now())
    margine = timedelta(minutes=MARGINE_MINUTI)
    for lz in sessione.lezioni.filter(data=adesso.date()).order_by("ora_inizio"):
        if _dt(lz.data, lz.ora_inizio) - margine <= adesso <= _dt(lz.data, lz.ora_fine) + margine:
            return lz
    return None


def lezione_di_oggi(sessione, adesso=None) -> TrainingLesson | None:
    adesso = timezone.localtime(adesso or timezone.now())
    return lezione_aperta(sessione, adesso) or sessione.lezioni.filter(data=adesso.date()).order_by("ora_inizio").first()


# ─────────────────────────────────────────────────────────────────────────────
# Chi firma: matricola + cognome, solo tra gli iscritti
# ─────────────────────────────────────────────────────────────────────────────

def identifica(sessione, matricola: str, cognome: str) -> TrainingEnrollment:
    from core.naming import chiave_testo

    from ..views import _helpers
    from .elearning_link_aperto import matricole_attive, norm_matricola

    mat = norm_matricola(matricola)
    ck = chiave_testo(cognome)
    if not mat or not ck:
        raise AulaError("Scrivi la matricola e il cognome come sul badge.")
    iscritti = list(sessione.iscrizioni.exclude(stato="RITIRATO"))
    per_id = {e.legacy_anagrafica_id: e for e in iscritti}
    trovati = [lid for lid, ms in matricole_attive(set(per_id)).items() if mat in ms]
    if not trovati:
        raise AulaError("Questa matricola non è tra gli iscritti alla sessione: avvisa il docente.")
    nomi = _helpers._build_nomi_map()
    for lid in trovati:
        if chiave_testo(nomi.get(lid, "")).startswith(ck) or ck in chiave_testo(nomi.get(lid, "")).split():
            return per_id[lid]
    raise AulaError("Matricola e cognome non corrispondono: controlla e riprova.")


# ─────────────────────────────────────────────────────────────────────────────
# Presenze
# ─────────────────────────────────────────────────────────────────────────────

def ore_da_orari(lezione, ingresso, uscita) -> Decimal:
    """Ore formative tra ingresso e uscita, dentro l'orario della lezione e mai oltre la sua durata."""
    if not ingresso or not uscita:
        return Decimal(str(lezione.durata_ore))
    inizio = max(datetime.combine(lezione.data, ingresso), datetime.combine(lezione.data, lezione.ora_inizio))
    fine = min(datetime.combine(lezione.data, uscita), datetime.combine(lezione.data, lezione.ora_fine))
    ore = max((fine - inizio).total_seconds() / 3600, 0)
    durata_lorda = (datetime.combine(lezione.data, lezione.ora_fine)
                    - datetime.combine(lezione.data, lezione.ora_inizio)).total_seconds() / 3600
    if lezione.pausa_minuti and durata_lorda and ore >= durata_lorda / 2:
        ore -= lezione.pausa_minuti / 60
    ore = min(max(ore, 0), float(lezione.durata_ore))
    return Decimal(str(ore)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _ricalcola(enrollment) -> None:
    from ..views.formazione import _ricalcola_presenza_enrollment
    try:
        _ricalcola_presenza_enrollment(enrollment)
    except Exception:
        logger.exception("Presenza dell'iscrizione %s non ricalcolata", enrollment.pk)


def firma_telefono(lezione, enrollment, adesso=None, ip: str = "") -> tuple[str, str]:
    """Firma d'ingresso o d'uscita dal telefono. Ritorna (cosa, "HH:MM")."""
    adesso = timezone.localtime(adesso or timezone.now())
    ora = adesso.time().replace(second=0, microsecond=0)
    with transaction.atomic():
        p, _ = TrainingLessonAttendance.objects.select_for_update().get_or_create(
            lezione=lezione, legacy_anagrafica_id=enrollment.legacy_anagrafica_id,
            defaults={"enrollment": enrollment, "stato_presenza": "PRESENTE"})
        if p.firma_ingresso and p.firma_uscita:
            raise AulaError(f"Hai già firmato ingresso ({p.ora_ingresso:%H:%M}) e uscita ({p.ora_uscita:%H:%M}).")
        if not p.firma_ingresso:
            cosa = "ingresso"
            p.firma_ingresso, p.ora_ingresso = True, ora
            if p.stato_presenza not in ("PRESENTE", "PARZIALE"):
                p.stato_presenza = "PRESENTE"
        else:
            entrata = _dt(lezione.data, p.ora_ingresso or lezione.ora_inizio)
            if adesso < entrata + timedelta(minutes=USCITA_DOPO_MINUTI) and adesso < _dt(lezione.data, lezione.ora_fine) - timedelta(minutes=MARGINE_MINUTI):
                raise AulaError(f"Ingresso già firmato alle {p.ora_ingresso:%H:%M}. L'uscita si firma a fine lezione.")
            cosa = "uscita"
            p.firma_uscita, p.ora_uscita = True, ora
            p.ore_effettive = ore_da_orari(lezione, p.ora_ingresso, ora)
            p.stato_presenza = "PRESENTE" if p.ore_effettive >= Decimal(str(lezione.durata_ore)) - Decimal("0.25") else "PARZIALE"
        p.signature_method = "DIGITALE"
        p.signature_status = "FIRMATO" if p.firma_ingresso else "PENDENTE"
        p.signed_at = adesso
        p.enrollment = p.enrollment or enrollment
        riga = f"Firma {cosa} dal telefono alle {ora:%H:%M}" + (f" (IP {ip})" if ip else "")
        p.note = (p.note + "\n" if p.note else "") + riga
        p.save()
    _ricalcola(enrollment)
    return cosa, f"{ora:%H:%M}"


def tutti_presenti(lezione, user) -> int:
    """Presente per chi è atteso alla lezione e non ha ancora una presenza registrata."""
    from .training_turni import iscritti_attesi_lezione

    if lezione.data and lezione.data > timezone.localdate():
        raise AulaError(f"La giornata del {lezione.data:%d/%m/%Y} non si è ancora svolta.")
    sessione = lezione.sessione
    tutte = list(sessione.iscrizioni.exclude(stato="RITIRATO").order_by("legacy_anagrafica_id"))
    attesi = iscritti_attesi_lezione(sessione, lezione, tutte)
    gia = set(TrainingLessonAttendance.objects.filter(lezione=lezione).values_list("legacy_anagrafica_id", flat=True))
    n = 0
    for e in attesi:
        if e.legacy_anagrafica_id in gia:
            continue
        TrainingLessonAttendance.objects.create(lezione=lezione, legacy_anagrafica_id=e.legacy_anagrafica_id,
                                                enrollment=e, stato_presenza="PRESENTE", registrato_da=user)
        _ricalcola(e)
        n += 1
    return n


def segna(lezione, enrollment, stato: str, user, ingresso=None, uscita=None) -> TrainingLessonAttendance:
    """Presenza in un tocco: PRESENTE, ASSENTE_INGIUST, ASSENTE_GIUST o PARZIALE (con gli orari)."""
    if stato not in dict(TrainingLessonAttendance.STATO_PRESENZA_CHOICES):
        raise AulaError("Stato di presenza non valido.")
    if lezione.data and lezione.data > timezone.localdate():
        raise AulaError(f"La giornata del {lezione.data:%d/%m/%Y} non si è ancora svolta.")
    p, _ = TrainingLessonAttendance.objects.get_or_create(
        lezione=lezione, legacy_anagrafica_id=enrollment.legacy_anagrafica_id,
        defaults={"enrollment": enrollment, "registrato_da": user})
    p.stato_presenza = stato
    p.registrato_da = user
    if stato == "PARZIALE":
        p.ora_ingresso = ingresso or p.ora_ingresso or lezione.ora_inizio
        p.ora_uscita = uscita or p.ora_uscita or lezione.ora_fine
        p.ore_effettive = ore_da_orari(lezione, p.ora_ingresso, p.ora_uscita)
    elif stato == "PRESENTE":
        p.ore_effettive = None
    else:
        p.ore_effettive = Decimal("0")
    p.save()
    _ricalcola(enrollment)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Test in aula (motore della lezione online, senza slide)
# ─────────────────────────────────────────────────────────────────────────────

def test_aperto(sessione) -> bool:
    from .sessione_online import config
    cfg = config(sessione)
    return bool(cfg and cfg.test_in_aula)


def apri_chiudi_test(sessione, aperto: bool):
    from .sessione_online import config, domande_valide
    cfg = config(sessione, crea=True)
    if aperto and not domande_valide(sessione):
        raise AulaError("Il test non ha domande: aggiungile in «Lezione online» o usa quelle del corso.")
    cfg.test_in_aula = aperto
    if aperto and not cfg.materiale_corso and not sessione.domande_online.exists():
        cfg.materiale_corso = True  # nessuna domanda propria: si usano quelle del corso
    cfg.save()
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Chiusura dell'edizione
# ─────────────────────────────────────────────────────────────────────────────

ESITI_SCELTA = [
    ("COMPLETATO", "Completato"),
    ("NON_IDONEO", "Non idoneo"),
    ("ASSENTE", "Assente"),
    ("RITIRATO", "Ritirato"),
    ("", "Da decidere"),
]


@dataclass
class RigaChiusura:
    enrollment: TrainingEnrollment
    nome: str
    ore: float
    pct_presenza: float | None
    test_pct: Decimal | None
    test_ok: bool | None
    proposto: str
    motivo: str = ""
    finale: bool = False


def _soglie(sessione) -> tuple[int, bool, int]:
    """(soglia presenza %, esame richiesto, soglia test %)."""
    from .sessione_online import config
    soglia_pres, esame = SOGLIA_PRESENZA_PREDEFINITA, False
    try:
        regola = sessione.corso.regola_superamento
        soglia_pres = int(regola.presenza_minima_percentuale or SOGLIA_PRESENZA_PREDEFINITA)
        esame = bool(regola.richiede_esame_finale)
    except Exception:
        pass
    cfg = config(sessione)
    return soglia_pres, esame, int(cfg.soglia_pct if cfg else 60)


def proposta(sessione) -> list[RigaChiusura]:
    from ..views import _helpers

    nomi = _helpers._build_nomi_map()
    soglia_pres, esame, _soglia_test = _soglie(sessione)
    ha_lezioni = sessione.lezioni.exists()
    # Lezione online scaduta: chi non ha superato il test non ha più tempo per farlo.
    online_scaduta = sessione.modalita == "ONLINE" and not ha_lezioni and online_finita(sessione)
    con_presenze = set(TrainingLessonAttendance.objects.filter(lezione__sessione=sessione)
                       .values_list("legacy_anagrafica_id", flat=True))
    righe = []
    for e in sessione.iscrizioni.order_by("legacy_anagrafica_id"):
        pct = float(e.percentuale_presenza) if e.percentuale_presenza is not None else None
        test_ok = e.verifica_superata
        r = RigaChiusura(e, nomi.get(e.legacy_anagrafica_id, f"#{e.legacy_anagrafica_id}"),
                         float(e.ore_frequentate or 0), pct, e.punteggio, test_ok, "")
        if e.stato in STATI_FINALI:
            r.proposto, r.finale = e.stato, True
        elif ha_lezioni and e.legacy_anagrafica_id not in con_presenze:
            r.motivo = "nessuna presenza registrata"
        elif ha_lezioni and pct is not None and pct < soglia_pres:
            r.proposto, r.motivo = "ASSENTE", f"presenza {pct:.0f}% sotto il {soglia_pres}%"
        elif test_ok is False:
            r.proposto, r.motivo = "NON_IDONEO", "test non superato"
        elif online_scaduta and test_ok is not True:
            r.proposto, r.motivo = "ASSENTE", "test non fatto entro la scadenza della lezione"
        elif esame and test_ok is not True:
            r.motivo = "il corso chiede la verifica finale: manca il test"
        elif not ha_lezioni and test_ok is not True:
            r.motivo = "nessuna giornata registrata: decidi tu"
        else:
            r.proposto = "COMPLETATO"
        righe.append(r)
    return righe


def registra_test_carta(enrollment, pct, soglia: int) -> None:
    pct = Decimal(str(pct)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if pct < 0 or pct > 100:
        raise AulaError("Il punteggio va da 0 a 100.")
    enrollment.punteggio = pct
    enrollment.punteggio_minimo = soglia
    enrollment.modalita_verifica = "TEST"
    enrollment.data_verifica = timezone.localdate()
    enrollment.verifica_superata = pct >= soglia
    enrollment.esito_esame = "Superato" if enrollment.verifica_superata else "Non superato"
    enrollment.save(update_fields=["punteggio", "punteggio_minimo", "modalita_verifica", "data_verifica",
                                   "verifica_superata", "esito_esame", "updated_at"])


@dataclass
class EsitoChiusura:
    completati: int = 0
    altri: int = 0
    aperti: int = 0
    bloccati: list[str] = field(default_factory=list)
    chiusa: bool = False


def chiudi(sessione, user, esiti: dict[int, str], carta: dict[int, str] | None = None) -> EsitoChiusura:
    """Applica gli esiti scelti; se nessuno resta aperto la sessione diventa «Completata»."""
    from ..views.formazione import _crea_employee_record, _motivi_blocco_completamento
    from .formazione_integrita import nome_utente

    if sessione.is_approvata:
        raise AulaError("L'edizione è già approvata: per cambiarla va riaperta.")
    out = EsitoChiusura()
    if sessione.modalita == "ONLINE":
        # Chi ha superato il test va a libretto con la data del test, non con quella di chiusura.
        from .sessione_online import registra_completamenti
        try:
            n_reg, bloccati = registra_completamenti(sessione, user)
            out.completati += n_reg
            out.bloccati += bloccati
        except Exception:
            logger.exception("Completamenti online non registrati alla chiusura (sessione %s)", sessione.pk)
    _soglia_pres, _esame, soglia_test = _soglie(sessione)
    oggi = timezone.localdate()
    data_c = min(sessione.data_fine or oggi, oggi)
    iscr = {e.pk: e for e in sessione.iscrizioni.select_related("sessione", "sessione__corso")}
    for eid, testo in (carta or {}).items():
        e = iscr.get(int(eid))
        if e is not None and str(testo).strip() != "" and e.stato not in STATI_FINALI:
            try:
                registra_test_carta(e, str(testo).replace(",", "."), soglia_test)
            except Exception as exc:  # noqa: BLE001 - punteggio illeggibile: si segnala
                out.bloccati.append(f"{e.legacy_anagrafica_id}: punteggio «{testo}» non valido ({exc})")
    for eid, stato in esiti.items():
        e = iscr.get(int(eid))
        if e is None or e.stato in STATI_FINALI or not stato:
            continue
        if stato not in dict(ESITI_SCELTA):
            continue
        with transaction.atomic():
            if stato == "COMPLETATO":
                if motivi := _motivi_blocco_completamento(e):
                    out.bloccati.append(f"#{e.legacy_anagrafica_id}: " + "; ".join(motivi))
                    continue
                e.stato, e.idoneo = "COMPLETATO", True
                e.data_completamento = e.data_completamento or data_c
                e.save(update_fields=["stato", "idoneo", "data_completamento", "updated_at"])
                _crea_employee_record(e, user)
                out.completati += 1
            else:
                e.stato = stato
                campi = ["stato", "updated_at"]
                if stato == "NON_IDONEO":
                    e.idoneo = False
                    campi.append("idoneo")
                e.save(update_fields=campi)
                out.altri += 1
    out.aperti = sessione.iscrizioni.filter(stato__in=STATI_APERTI).count()
    if not out.aperti and sessione.stato != "COMPLETATA":
        sessione.stato = "COMPLETATA"
        sessione.chiusa_il = timezone.now()
        sessione.chiusa_da_nome = nome_utente(user)[:160]
        sessione.save(update_fields=["stato", "chiusa_il", "chiusa_da_nome", "updated_at"])
        out.chiusa = True
        from .sessione_online import config
        cfg = config(sessione)
        if cfg and cfg.test_in_aula:
            cfg.test_in_aula = False
            cfg.save(update_fields=["test_in_aula", "updated_at"])
    elif not out.aperti:
        out.chiusa = True
        if not sessione.chiusa_il:
            # Già «Completata» (es. dalla modifica della sessione) ma mai chiusa da qui: la data
            # di chiusura serve alla coda MOD.040 e al registro.
            sessione.chiusa_il = timezone.now()
            sessione.chiusa_da_nome = nome_utente(user)[:160]
            sessione.save(update_fields=["chiusa_il", "chiusa_da_nome", "updated_at"])
    return out


def chiudi_con_proposta(sessione, user) -> EsitoChiusura:
    """Chiusura in blocco: applica solo gli esiti che il portale sa proporre."""
    return chiudi(sessione, user, {r.enrollment.pk: r.proposto for r in proposta(sessione) if r.proposto and not r.finale})


def annulla(sessione) -> None:
    if sessione.iscrizioni.filter(stato="COMPLETATO").exists() or sessione.record_completamenti.exists():
        raise AulaError(f"{sessione.codice_sessione}: ha già dei completamenti, non si annulla.")
    sessione.stato = "ANNULLATA"
    sessione.save(update_fields=["stato", "updated_at"])


STATI_NON_CHIUSI = ("PIANIFICATA", "IN_CORSO")


def q_finite(oggi):
    """Edizioni finite: l'ultima giornata è passata; per le online (slide + test) conta la
    scadenza della lezione, se c'è, al posto della data di fine."""
    from django.db.models import Q
    return (Q(data_fine__lt=oggi) & ~Q(modalita="ONLINE")
            | Q(modalita="ONLINE", lezione_online__scadenza__lt=oggi)
            | Q(modalita="ONLINE", lezione_online__scadenza__isnull=True, data_fine__lt=oggi))


def da_chiudere(oggi=None):
    """Edizioni finite e non ancora chiuse. Unica definizione: elenco «Da chiudere» e controllo
    «Edizioni finite e non chiuse» dell'Integrità dati contano le stesse."""
    oggi = oggi or timezone.localdate()
    return TrainingSession.objects.filter(q_finite(oggi), stato__in=STATI_NON_CHIUSI)


def aggiorna_stati(oggi=None) -> int:
    """Stato automatico: «Pianificata» diventa «In corso» il giorno in cui l'edizione inizia.

    Chiamata all'apertura dell'elenco e della pagina sessione e dal promemoria quotidiano;
    la fine non cambia lo stato: l'edizione finita compare in «Da chiudere» finché qualcuno
    non registra gli esiti. Ritorna quante edizioni ha aggiornato."""
    oggi = oggi or timezone.localdate()
    try:
        return TrainingSession.objects.filter(stato="PIANIFICATA", data_inizio__lte=oggi).update(stato="IN_CORSO")
    except Exception:
        logger.exception("Stato automatico delle edizioni non aggiornato")
        return 0


def scadenza_online(sessione):
    """Ultimo giorno della lezione online: la scadenza impostata, altrimenti la data di fine."""
    from .sessione_online import config
    cfg = config(sessione)
    return (cfg.scadenza if cfg and cfg.scadenza else None) or sessione.data_fine


def online_finita(sessione, oggi=None) -> bool:
    oggi = oggi or timezone.localdate()
    fine = scadenza_online(sessione)
    return bool(fine and fine < oggi)


def cosa_manca_breve(sessione) -> tuple[str, str]:
    """(testo, tono) per la colonna «Cosa manca» dell'elenco Da chiudere."""
    n = getattr(sessione, "n_iscritti_tot", None)
    if n is None:
        n = sessione.iscrizioni.count()
    if not n:
        return "nessun iscritto: da annullare?", "grey"
    aperti = getattr(sessione, "n_aperti", None)
    if aperti is None:
        aperti = sessione.iscrizioni.filter(stato__in=STATI_APERTI).count()
    if not aperti:
        return "esiti tutti dati: solo da chiudere", "ok"
    return f"esito di {aperti} person{'a' if aperti == 1 else 'e'}", "warn"


# ─────────────────────────────────────────────────────────────────────────────
# Fasi della pagina sessione
# ─────────────────────────────────────────────────────────────────────────────

def fase(sessione, oggi=None) -> str:
    """prima · durante · dopo. Le online (slide + test) restano «durante» fino alla scadenza."""
    oggi = oggi or timezone.localdate()
    if sessione.is_chiusa:
        return "dopo"
    if sessione.modalita == "ONLINE":
        if online_finita(sessione, oggi):
            return "dopo"
        from .sessione_online import config
        cfg = config(sessione)
        if cfg and cfg.pubblicata_il and (not sessione.data_inizio or sessione.data_inizio <= oggi):
            return "durante"
        return "prima"
    if sessione.data_fine and sessione.data_fine < oggi:
        return "dopo"
    if sessione.data_inizio and sessione.data_inizio <= oggi:
        return "durante"
    return "prima"


# ─────────────────────────────────────────────────────────────────────────────
# Efficacia (§9.5) e approvazioni (§9.3) per «Le mie attività»
# ─────────────────────────────────────────────────────────────────────────────

ANTICIPO_GIORNI_EFFICACIA = 15


def efficacie_da_valutare(capo_legacy_id: int | None = None, *, tutte: bool = False, oggi=None) -> list:
    """Valutazioni dovute o in arrivo entro 15 giorni: del capo indicato (le persone di cui è il
    capo) o tutte. Stessa regola di ``formazione_efficacia.valutazioni_da_fare`` (fonte unica)."""
    from .capo_team import mappa_capi
    from .formazione_efficacia import valutazioni_da_fare

    oggi = oggi or timezone.localdate()
    qs = list(valutazioni_da_fare(oggi=oggi, anticipo_giorni=ANTICIPO_GIORNI_EFFICACIA))
    if tutte or not qs:
        return qs
    if not capo_legacy_id:
        return []
    try:
        mappa = mappa_capi()
    except Exception:
        logger.exception("Mappa dei capi non calcolata")
        return []
    return [v for v in qs if getattr(mappa.get(v.legacy_anagrafica_id), "legacy_id", None) == int(capo_legacy_id)]


METODI_EFFICACIA = [("TEST", "Test teorico"), ("PRATICA", "Prova pratica supervisionata"),
                    ("CAMPO", "Verifica della prestazione sul campo")]


def salva_efficacia(valutazione, esito: str, user, metodo: str = "", azione: str = "", note: str = "") -> None:
    from .formazione_integrita import nome_utente

    if esito not in dict(TrainingEfficacia.ESITO_CHOICES):
        raise AulaError("Scegli un esito.")
    if esito != "EFFICACE" and not (azione or "").strip():
        raise AulaError("Se l'esito non è pieno scrivi cosa si fa (affiancamento, nuovo addestramento…).")
    metodo_txt = dict(METODI_EFFICACIA).get(metodo, "")
    valutazione.esito = esito
    valutazione.azione = (azione or "").strip()
    valutazione.note = "\n".join(x for x in (f"Verificata con: {metodo_txt}" if metodo_txt else "", (note or "").strip()) if x)
    valutazione.valutata_il = timezone.localdate()
    valutazione.valutata_da = user if getattr(user, "is_authenticated", False) else None
    valutazione.valutatore_nome = nome_utente(user)[:200]
    valutazione.save()


def q_da_approvare():
    """Coda MOD.040: edizioni «Completata» non ancora approvate, chiuse da qui o no."""
    from django.db.models import Q
    return Q(stato="COMPLETATA", approvata_il__isnull=True)


def edizioni_da_approvare():
    return (TrainingSession.objects.filter(q_da_approvare())
            .select_related("corso").order_by("-data_fine", "-id"))


def verifiche_nc_dovute(oggi=None) -> list:
    from .formazione_efficacia import aggiungi_mesi
    oggi = oggi or timezone.localdate()
    out = []
    for s in (TrainingSession.objects.filter(approvata_il__isnull=False, chiusa_il__isnull=False, verifica_nc_esito="")
              .select_related("corso").order_by("data_fine")):
        if s.data_fine and aggiungi_mesi(s.data_fine, TrainingSession.MESI_VERIFICA_NC) <= oggi:
            out.append(s)
    return out
