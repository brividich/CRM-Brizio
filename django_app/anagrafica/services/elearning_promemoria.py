"""Scaletta dei promemoria e-learning (prompt 05, fase 2).

Vale per le **assegnazioni con scadenza** su corsi pubblicati e non ancora
completate nel ciclo:

- **prima della scadenza** (``ElearningConfig.promemoria_giorni_prima``, es.
  14/7/1): notifica in-app al dipendente;
- **dopo la scadenza** (``solleciti_giorni_dopo``, es. 1/7/14): notifica al
  dipendente e sollecito al **responsabile** (in-app ed email di notifica);
- **digest settimanale** al responsabile (``digest_responsabile_giorno``): i suoi
  corsi in scadenza entro la soglia più lunga e quelli scaduti, in un'unica email.

Niente doppioni: ogni avviso ha una chiave univoca (``TrainingElearningAvviso``).
Si manda la soglia più urgente già raggiunta e non ancora inviata, così un giorno
saltato dal job non produce una raffica di avvisi arretrati. I dipendenti cessati
non ricevono nulla. Il responsabile è quello effettivo (area aziendale, poi
caporeparto), lo stesso usato dal resto del modulo.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def soglie(testo: str) -> list[int]:
    """«14, 7,1» → [14, 7, 1] (positivi, senza doppioni, dal più grande)."""
    out = set()
    for pezzo in str(testo or "").replace(";", ",").split(","):
        pezzo = pezzo.strip()
        if pezzo.isdigit() and 0 < int(pezzo) <= 365:
            out.add(int(pezzo))
    return sorted(out, reverse=True)


@dataclass
class Voce:
    corso: object
    legacy_anagrafica_id: int
    ciclo: int
    scadenza: date

    def giorni(self, oggi: date) -> int:
        return (self.scadenza - oggi).days


@dataclass
class Riepilogo:
    promemoria: int = 0
    solleciti: int = 0
    email_responsabili: int = 0
    digest: int = 0
    senza_responsabile: list = field(default_factory=list)


def voci_aperte() -> list[Voce]:
    """Assegnazioni aperte con scadenza, su corsi pubblicati, non completate, di non cessati."""
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment
    from .elearning_fruizione import filtro_pubblicati
    from .organigramma_albero import cessati_legacy_ids

    pubblicati = filtro_pubblicati("corso__")
    completati = set(TrainingElearningEnrollment.objects.filter(stato="COMPLETATO", **pubblicati)
                     .values_list("corso_id", "legacy_anagrafica_id", "ciclo"))
    cessati = cessati_legacy_ids()
    voci = {}
    for a in (TrainingAssignment.objects
              .filter(stato__in=["ASSEGNATO", "IN_CORSO", "SCADUTO"], due_date__isnull=False, **pubblicati)
              .select_related("corso").order_by("due_date", "pk")):
        chiave = (a.corso_id, a.legacy_anagrafica_id, a.ciclo)
        if chiave in completati or chiave in voci or a.legacy_anagrafica_id in cessati:
            continue
        voci[chiave] = Voce(a.corso, a.legacy_anagrafica_id, a.ciclo, a.due_date)
    return list(voci.values())


def _registra(chiave: str, *, invia: bool = True, **campi) -> bool:
    """Crea l'avviso; False se c'era già (è il lucchetto anti-doppione).

    In prova (``invia=False``) non scrive nulla: dice solo se partirebbe."""
    from ..models_elearning import TrainingElearningAvviso

    if not invia:
        return not TrainingElearningAvviso.objects.filter(chiave=chiave[:160]).exists()
    try:
        with transaction.atomic():
            TrainingElearningAvviso.objects.create(chiave=chiave[:160], **campi)
    except IntegrityError:
        return False
    return True


def _soglia_prima(giorni: int, scaletta: list[int]) -> int | None:
    """La soglia più urgente già raggiunta prima della scadenza (giorni ≥ 0)."""
    raggiunte = [t for t in scaletta if giorni <= t]
    return min(raggiunte) if raggiunte and giorni >= 0 else None


MARGINE_SOLLECITI = 7


def _soglia_dopo(giorni: int, scaletta: list[int]) -> int | None:
    """La soglia più alta raggiunta; nessun sollecito per ritardi ben oltre l'ultima
    (scaduti storici al primo avvio: li vede il responsabile nel riepilogo)."""
    ritardo = -giorni
    raggiunte = [t for t in scaletta if ritardo >= t]
    if not raggiunte or ritardo > max(scaletta) + MARGINE_SOLLECITI:
        return None
    return max(raggiunte)


def _nomi(legacy_ids) -> dict[int, str]:
    from core import naming
    from core.legacy_models import AnagraficaDipendente

    return {r["id"]: naming.nome_completo(r["nome"], r["cognome"])
            for r in AnagraficaDipendente.objects.filter(pk__in=list(legacy_ids)).values("id", "nome", "cognome")}


def _email_responsabile(legacy_id: int) -> str:
    from core.caporeparto_digest import capo_notification_email
    return capo_notification_email(legacy_id)


def _manda_email(destinatario: str, oggetto: str, testo: str, sezioni) -> bool:
    from automazioni.mail_config import apply_mail_overrides
    from core.email_utils import send_hub_mail

    from .email_digest import digest_fragment

    frammento = digest_fragment(sezioni)
    oggetto, testo, frammento, piede = apply_mail_overrides(
        "elearning_reminders", subject=oggetto, body_text=testo, fragment=frammento)
    try:
        send_hub_mail(oggetto, testo, [destinatario], email_type="Anagrafica HR",
                      section_label="Formazione e-learning", body_html_fragment=frammento,
                      footer_note=piede, fail_silently=False)
        return True
    except Exception:
        logger.exception("[e-learning] email al responsabile non inviata")
        return False


def esegui(*, oggi: date | None = None, invia: bool = True) -> Riepilogo:
    from core.notifiche import invia_notifica

    from ..models_formazione import ElearningConfig
    from .elearning_notifications import utente_di
    from .reparto_canonico import build_responsabile_effettivo_map

    oggi = oggi or timezone.localdate()
    cfg = ElearningConfig.get_instance()
    prima, dopo = soglie(cfg.promemoria_giorni_prima), soglie(cfg.solleciti_giorni_dopo)
    voci = voci_aperte()
    rie = Riepilogo()
    if not voci:
        return rie
    responsabili = build_responsabile_effettivo_map(sorted({v.legacy_anagrafica_id for v in voci}))
    nomi = _nomi({v.legacy_anagrafica_id for v in voci})
    solleciti_per_resp: dict[int, list[tuple[Voce, int]]] = defaultdict(list)

    for v in voci:
        g = v.giorni(oggi)
        url = reverse("anagrafica:formazione_online_player", args=[v.corso.pk])
        base = f"c{v.corso.pk}:d{v.legacy_anagrafica_id}:k{v.ciclo}"
        t = _soglia_prima(g, prima)
        if t is not None and _registra(f"prima:{t}:{base}", invia=invia, tipo="PRIMA", corso=v.corso,
                                       legacy_anagrafica_id=v.legacy_anagrafica_id, ciclo=v.ciclo, giorni=t):
            rie.promemoria += 1
            if invia:
                quando = "oggi" if g == 0 else ("domani" if g == 1 else f"fra {g} giorni")
                invia_notifica(utente_di(v.legacy_anagrafica_id), "elearning_promemoria",
                               f"Corso online da completare entro {quando} ({v.scadenza:%d/%m/%Y}): {v.corso.titolo}.",
                               url)
        t = _soglia_dopo(g, dopo)
        if t is not None:
            resp = responsabili.get(v.legacy_anagrafica_id)
            if _registra(f"dopo:{t}:{base}", invia=invia, tipo="SOLLECITO", corso=v.corso,
                         legacy_anagrafica_id=v.legacy_anagrafica_id, ciclo=v.ciclo, giorni=-t,
                         responsabile_legacy_id=resp):
                rie.solleciti += 1
                if invia:
                    invia_notifica(utente_di(v.legacy_anagrafica_id), "elearning_sollecito",
                                   f"Corso online scaduto il {v.scadenza:%d/%m/%Y}: completalo appena puoi. "
                                   f"{v.corso.titolo}.", url)
                if resp:
                    solleciti_per_resp[resp].append((v, -g))
                else:
                    rie.senza_responsabile.append(v.legacy_anagrafica_id)

    # Sollecito al responsabile: una notifica e una email per responsabile e giorno,
    # con tutte le persone che hanno superato una soglia oggi.
    for resp, righe in solleciti_per_resp.items():
        if not invia:
            continue
        elenco = "; ".join(f"{nomi.get(v.legacy_anagrafica_id, f'#{v.legacy_anagrafica_id}')} — {v.corso.titolo}"
                           for v, _ in righe)
        invia_notifica(utente_di(resp), "elearning_sollecito_responsabile",
                       f"Corsi online scaduti nel tuo gruppo: {elenco}.", reverse("anagrafica:elearning_cruscotto"))
        email = _email_responsabile(resp)
        if email:
            testo = "\n".join(f"- {nomi.get(v.legacy_anagrafica_id, '')}: {v.corso.titolo}, scaduto il "
                              f"{v.scadenza:%d/%m/%Y} ({r} giorni fa)" for v, r in righe)
            sezioni = [("Corsi online scaduti", [{
                "title": nomi.get(v.legacy_anagrafica_id, f"Dipendente #{v.legacy_anagrafica_id}"),
                "subtitle": v.corso.titolo, "note": f"Scaduto il {v.scadenza:%d/%m/%Y} ({r} giorni fa)",
                "accent": "#e8590c"} for v, r in righe])]
            if _manda_email(email, f"[E-LEARNING] {len(righe)} corsi scaduti nel tuo gruppo", testo, sezioni):
                rie.email_responsabili += 1

    if cfg.digest_responsabile_giorno == oggi.weekday():
        rie.digest = _digest_settimanale(voci, responsabili, nomi, oggi, max(prima or [0]), invia=invia)
    return rie


def _digest_settimanale(voci, responsabili, nomi, oggi, orizzonte, *, invia) -> int:
    anno, settimana, _ = oggi.isocalendar()
    per_resp: dict[int, list[Voce]] = defaultdict(list)
    for v in voci:
        resp = responsabili.get(v.legacy_anagrafica_id)
        if resp and v.giorni(oggi) <= orizzonte:
            per_resp[resp].append(v)
    inviati = 0
    for resp, elenco in per_resp.items():
        email = _email_responsabile(resp)
        if not email or not _registra(f"digest:r{resp}:{anno}-W{settimana:02d}", invia=invia, tipo="DIGEST",
                                      responsabile_legacy_id=resp, email_inviata=True):
            continue
        if not invia:
            inviati += 1
            continue
        scaduti = [v for v in elenco if v.giorni(oggi) < 0]
        in_scadenza = [v for v in elenco if v.giorni(oggi) >= 0]
        sezioni = []
        for titolo, gruppo, colore in (("Scaduti", scaduti, "#e8590c"), ("In scadenza", in_scadenza, "#2563eb")):
            if gruppo:
                sezioni.append((f"{titolo} ({len(gruppo)})", [{
                    "title": nomi.get(v.legacy_anagrafica_id, f"Dipendente #{v.legacy_anagrafica_id}"),
                    "subtitle": v.corso.titolo, "note": f"Scadenza {v.scadenza:%d/%m/%Y}", "accent": colore,
                } for v in gruppo]))
        testo = "\n".join(f"- {nomi.get(v.legacy_anagrafica_id, '')}: {v.corso.titolo} entro {v.scadenza:%d/%m/%Y}"
                          for v in elenco)
        if _manda_email(email, f"[E-LEARNING] Riepilogo settimanale: {len(scaduti)} scaduti, "
                               f"{len(in_scadenza)} in scadenza", testo, sezioni):
            inviati += 1
        else:  # email non partita: si riprova al prossimo giro
            from ..models_elearning import TrainingElearningAvviso
            TrainingElearningAvviso.objects.filter(chiave=f"digest:r{resp}:{anno}-W{settimana:02d}").delete()
    return inviati
