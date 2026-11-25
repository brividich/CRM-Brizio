"""Link aperto di un corso e-learning: fruizione senza login per chi non ha un utente del portale.

Flusso (``anagrafica/views_corso_aperto.py``, prefisso pubblico ``/corso-aperto/``):

1. l'HR attiva il link nella gestione del corso; il token è lungo e si rigenera;
2. slide e video si servono **in ordine**, una per volta; quali slide sono state
   aperte e da quando lo ricorda la sessione del browser (nessun dato personale);
3. il quiz si apre solo dopo l'ultima slide (e dopo il tempo minimo della regola del
   corso, misurato dal server); in fondo al quiz la persona scrive nome e cognome;
4. alla consegna il quiz si corregge come quello dei dipendenti con login e si salva
   una ``TrainingElearningRispostaAperta``;
5. **abbinamento automatico**: se nome e cognome (in qualunque ordine, senza accenti
   né maiuscole) corrispondono a un solo dipendente attivo, la risposta si abbina e,
   se il quiz è superato, nasce il completamento (``TrainingEmployeeRecord``) come
   per l'e-learning con login; altrimenti resta «Da abbinare» per il controllo HR.

Il controllo HR (gestione del corso) vede tutte le risposte: può abbinare a mano,
correggere un abbinamento sbagliato (il completamento creato viene annullato con
motivo, non cancellato) o scartare una risposta.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.naming import chiave_testo, chiavi_confronto, nome_completo

import logging
logger = logging.getLogger(__name__)

MOTIVO_CORREZIONE = "Link aperto: abbinamento corretto dall'HR"
MOTIVO_SCARTO = "Link aperto: risposta scartata dall'HR"


def nuovo_token() -> str:
    return secrets.token_urlsafe(24)


def link_valido(token: str):
    """Il link attivo e non scaduto con questo token, con il corso pubblicato; altrimenti None."""
    from ..models_elearning import TrainingElearningLinkAperto
    from .elearning_fruizione import corso_pubblicato

    if not token or len(token) > 64:
        return None
    link = TrainingElearningLinkAperto.objects.select_related("corso").filter(token=token, attivo=True).first()
    if link is None or not link.corso.is_elearning or not corso_pubblicato(link.corso):
        return None
    if link.scade_il and timezone.localdate() > link.scade_il:
        return None
    return link


def attiva_o_rigenera(corso, user, *, rigenera: bool = False, scade_il=None):
    from ..models_elearning import TrainingElearningLinkAperto

    link = TrainingElearningLinkAperto.objects.filter(corso=corso).first()
    if link is None:
        return TrainingElearningLinkAperto.objects.create(corso=corso, token=nuovo_token(), creato_da=user,
                                                          scade_il=scade_il)
    if rigenera:
        link.token = nuovo_token()
    link.attivo = True
    link.scade_il = scade_il
    link.save(update_fields=["token", "attivo", "scade_il", "aggiornato_il"])
    return link


# ── Abbinamento ─────────────────────────────────────────────────────────────

def dipendenti_attivi() -> list[dict]:
    """[{id, nome}] dei dipendenti non cessati, ordinati per nome."""
    from core.legacy_models import AnagraficaDipendente

    from ..models import DipendenteAnagraficaAziendale

    cessati = set(DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
                  .values_list("legacy_anagrafica_id", flat=True))
    out = []
    for r in AnagraficaDipendente.objects.values("id", "nome", "cognome"):
        if not r["id"] or r["id"] in cessati:
            continue
        out.append({"id": int(r["id"]), "nome": nome_completo(r["nome"], r["cognome"]) or f"#{r['id']}",
                    "chiave": chiave_testo(f"{r['cognome'] or ''} {r['nome'] or ''}")})
    return sorted(out, key=lambda d: d["nome"].casefold())


def candidati(nome: str, cognome: str, attivi: list[dict] | None = None) -> list[int]:
    """Id dei dipendenti attivi con lo stesso nome e cognome (ordine, accenti e maiuscole non contano)."""
    chiavi = chiavi_confronto(nome, cognome)
    if not chiavi:
        return []
    attivi = dipendenti_attivi() if attivi is None else attivi
    return sorted({d["id"] for d in attivi if d["chiave"] in chiavi})


def norm_matricola(valore: str) -> str:
    """Matricola confrontabile: maiuscole, solo lettere e cifre, senza zeri iniziali.

    ``t 138``, ``T138`` e ``000000T138`` danno ``T138``; ``0000CNO123`` dà ``CNO123``."""
    import re
    testo = re.sub(r"[^A-Z0-9]", "", str(valore or "").upper())
    return testo.lstrip("0") or ("0" if testo else "")


def matricole_attive(ids: set[int]) -> dict[int, set[str]]:
    """{legacy_id: matricole normalizzate}: anagrafica del portale, poi dati delle presenze (timbri)."""
    from core.legacy_anagrafica import fetch_anagrafica_rows

    out: dict[int, set[str]] = {}
    try:
        for r in fetch_anagrafica_rows(ids=sorted(ids)):
            m = norm_matricola(r.get("matricola") or "")
            if m and r.get("id"):
                out.setdefault(int(r["id"]), set()).add(m)
    except Exception:
        logger.exception("Matricole dell'anagrafica non leggibili")
    try:
        from timbri.models import OperatoreTimbri
        for lid, m in (OperatoreTimbri.objects.filter(legacy_anagrafica_id__in=ids)
                       .exclude(matricola="").values_list("legacy_anagrafica_id", "matricola")):
            if norm_matricola(m):
                out.setdefault(int(lid), set()).add(norm_matricola(m))
    except Exception:
        logger.exception("Matricole dei timbri non leggibili")
    return out


def abbinamento_con_matricola(nome: str, cognome: str, matricola: str,
                              attivi: list[dict] | None = None, reparto: str = "") -> tuple[int | None, str]:
    """(legacy_id, nota). Abbina solo se matricola e cognome indicano la stessa persona.

    - matricola di una persona attiva con lo stesso cognome → quella persona;
    - matricola di una persona con cognome diverso → nessuno («è di un'altra persona»);
    - matricola sconosciuta → nome e cognome, ma solo se la persona trovata non ha matricole
      registrate (altrimenti è un errore di battitura da controllare)."""
    attivi = dipendenti_attivi() if attivi is None else attivi
    per_id = {d["id"]: d for d in attivi}
    mat = norm_matricola(matricola)
    matricole = matricole_attive(set(per_id))
    ck = chiave_testo(cognome)
    if mat:
        con_mat = [lid for lid, ms in matricole.items() if mat in ms]
        if con_mat:
            def stesso_cognome(lid):
                chiave = per_id[lid]["chiave"]  # «COGNOME NOME»
                return bool(ck) and (chiave == ck or chiave.startswith(ck + " ") or ck in chiave.split())
            giusti = [lid for lid in con_mat if stesso_cognome(lid)]
            if len(giusti) == 1:
                return giusti[0], ""
            if not giusti:
                return None, f"La matricola {matricola} è di un'altra persona: controlla nome e matricola."
            return None, f"La matricola {matricola} risulta a più persone."
    trovati = candidati(nome, cognome, attivi)
    if len(trovati) > 1 and reparto:
        # QR di reparto: tra gli omonimi vale chi sta in quel reparto.
        from ..models import DipendenteAnagraficaAziendale
        del_reparto = set(DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id__in=trovati, area__iexact=reparto).values_list("legacy_anagrafica_id", flat=True))
        if len(del_reparto) == 1:
            trovati = sorted(del_reparto)
    if len(trovati) == 1 and not matricole.get(trovati[0]):
        return trovati[0], ""
    if len(trovati) == 1:
        return None, f"Matricola {matricola or '(vuota)'} non trovata per {cognome} {nome}: verifica."
    return None, ("Nessun dipendente attivo con questo nome e questa matricola." if not trovati
                  else f"{len(trovati)} dipendenti con questo nome e matricola non riconosciuta.")


def _record_esistente(corso, legacy_id: int):
    """Completamento già nato dal link aperto per la stessa persona e la stessa versione del corso."""
    from ..models_elearning import TrainingElearningRispostaAperta

    prec = (TrainingElearningRispostaAperta.objects
            .filter(corso=corso, legacy_anagrafica_id=legacy_id, record__isnull=False,
                    record__annullato_il__isnull=True, record__course_version_snapshot=corso.versione)
            .select_related("record").first())
    return prec.record if prec else None


def _completa(risposta, legacy_id: int, user):
    """Crea (o riusa) il completamento per un quiz superato. Ritorna il record."""
    from ..models_formazione import TrainingAssignment
    from ..views import _crea_record_completamento_elearning

    corso = risposta.corso
    record = _record_esistente(corso, legacy_id)
    if record is None:
        tentativo = _TentativoFinto(risposta)
        record = _crea_record_completamento_elearning(corso, legacy_id, tentativo, user)
        nota = (f"Completato dal link aperto (nome scritto: {risposta.cognome} {risposta.nome}); "
                f"risposta #{risposta.pk}.")
        type(record).objects.filter(pk=record.pk).update(note=((record.note + "\n") if record.note else "") + nota)
    TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).exclude(
        stato__in=("COMPLETATO", "ESONERATO")).update(stato="COMPLETATO")
    return record


@dataclass
class _TentativoFinto:
    """Quel che ``_crea_record_completamento_elearning`` legge di un tentativo di quiz."""
    risposta: object

    @property
    def punteggio_pct(self):
        return self.risposta.punteggio_pct

    @property
    def n_corrette(self):
        return self.risposta.n_corrette

    @property
    def n_totali(self):
        return self.risposta.n_totali


def abbina(risposta, legacy_id: int, *, user=None, stato: str = "MANUALE") -> None:
    """Abbina la risposta a un dipendente; con quiz superato crea il completamento.

    Se era già abbinata a un'altra persona, il completamento precedente viene annullato
    con motivo (resta nello storico)."""
    from ..models_elearning import TrainingElearningRispostaAperta as R

    with transaction.atomic():
        risposta = R.objects.select_for_update().select_related("corso", "record").get(pk=risposta.pk)
        if risposta.legacy_anagrafica_id == legacy_id and risposta.stato in (R.AUTO, R.MANUALE):
            return
        _annulla_record(risposta, user, MOTIVO_CORREZIONE)
        risposta.legacy_anagrafica_id = legacy_id
        risposta.stato = stato
        risposta.abbinata_da = user if getattr(user, "is_authenticated", False) else None
        risposta.abbinata_il = timezone.now()
        risposta.record = _completa(risposta, legacy_id, user) if risposta.superato else None
        risposta.save(update_fields=["legacy_anagrafica_id", "stato", "abbinata_da", "abbinata_il", "record"])


def scarta(risposta, *, user, nota: str = "") -> None:
    from ..models_elearning import TrainingElearningRispostaAperta as R

    with transaction.atomic():
        risposta = R.objects.select_for_update().select_related("record").get(pk=risposta.pk)
        _annulla_record(risposta, user, MOTIVO_SCARTO)
        risposta.stato = R.SCARTATA
        risposta.record = None
        risposta.abbinata_da = user
        risposta.abbinata_il = timezone.now()
        risposta.nota = (nota or "").strip()[:300]
        risposta.save(update_fields=["stato", "record", "abbinata_da", "abbinata_il", "nota"])


def _annulla_record(risposta, user, motivo: str) -> None:
    """Annulla il completamento della risposta se nessun'altra risposta lo usa ancora."""
    from ..models_elearning import TrainingElearningRispostaAperta as R
    from .formazione_integrita import annulla_record

    record = risposta.record
    if record is None or record.is_annullato:
        return
    if R.objects.filter(record=record).exclude(pk=risposta.pk).exists():
        return
    annulla_record(record, user, motivo)


# ── Consegna del quiz ───────────────────────────────────────────────────────

def correggi(corso, domande_ids: list[int], risposte: dict[int, set[int]], soglia_pct) -> dict:
    """Correzione come il quiz con login (``elearning_quiz._correggi_aperto``): una domanda è
    giusta solo se le opzioni scelte coincidono con quelle corrette."""
    from ..models_formazione import TrainingQuizOption, TrainingQuizQuestion

    domande = {d.pk: d for d in TrainingQuizQuestion.objects.filter(corso=corso, pk__in=domande_ids)}
    opzioni: dict[int, set[int]] = {}
    corrette: dict[int, set[int]] = {}
    for o in TrainingQuizOption.objects.filter(domanda_id__in=list(domande)):
        opzioni.setdefault(o.domanda_id, set()).add(o.pk)
        if o.corretta:
            corrette.setdefault(o.domanda_id, set()).add(o.pk)
    snapshot, n_corrette = [], 0
    for did in domande_ids:
        if did not in domande:
            continue
        scelte = (risposte.get(did) or set()) & opzioni.get(did, set())
        giuste = corrette.get(did, set())
        ok = bool(giuste) and scelte == giuste
        n_corrette += ok
        snapshot.append({"domanda_id": did, "domanda": domande[did].testo, "scelte": sorted(scelte),
                         "corrette": sorted(giuste), "giusta": ok})
    n_totali = len(snapshot)
    punteggio = Decimal(str(round(n_corrette / n_totali * 100, 2))) if n_totali else Decimal("0")
    return {"n_corrette": n_corrette, "n_totali": n_totali, "punteggio_pct": punteggio,
            "superato": bool(n_totali) and punteggio >= Decimal(str(soglia_pct)), "risposte": snapshot}


def nuova_partecipazione(link, dati: dict, *, reparto: str = "", ip: str = ""):
    """Crea la partecipazione alla registrazione e prova subito l'abbinamento (matricola + cognome)."""
    from ..models_elearning import TrainingElearningPartecipazioneAperta as P

    legacy_id, nota = abbinamento_con_matricola(dati["nome"], dati["cognome"], dati.get("matricola", ""),
                                                reparto=reparto)
    return P.objects.create(corso=link.corso, nome=dati["nome"], cognome=dati["cognome"],
                            matricola=(dati.get("matricola") or "")[:40], reparto=(reparto or "")[:120],
                            legacy_anagrafica_id=legacy_id, nota_abbinamento=(nota or "")[:300],
                            ip=ip or None)


def chiede_pin(link) -> bool:
    return bool(getattr(link, "chiedi_pin", False))


def controlla_pin(link, dati: dict, pin: str) -> str:
    """Con «Chiedi il PIN» acceso: chi ha un PIN delle postazioni condivise deve scriverlo giusto.

    Chi non ha l'utente del portale non ha PIN e passa con la sola matricola."""
    if not chiede_pin(link):
        return ""
    legacy_id, _nota = abbinamento_con_matricola(dati["nome"], dati["cognome"], dati.get("matricola", ""))
    if not legacy_id:
        return ""
    from core.legacy_models import AnagraficaDipendente
    from core.models import PinPostazione
    utente_id = AnagraficaDipendente.objects.filter(pk=legacy_id).values_list("utente_id", flat=True).first()
    if not utente_id or not PinPostazione.objects.filter(legacy_user_id=utente_id).exists():
        return ""
    if not (pin or "").strip():
        return "Hai un PIN delle postazioni condivise: scrivilo per continuare."
    from core.postazioni import verifica_pin
    esito = verifica_pin(utente_id, pin)
    if esito.get("esito") == "ok":
        return ""
    if esito.get("esito") == "bloccato":
        return "PIN bloccato per troppi errori: chiedi all'ufficio HR."
    return f"PIN non corretto (tentativi rimasti: {esito.get('restanti', 0)})."


def registra(corso, *, nome: str, cognome: str, esito: dict, avviato_il, ip: str, user_agent: str,
             matricola: str = "", partecipazione=None):
    """Salva la risposta e prova l'abbinamento automatico (matricola + cognome). Ritorna la risposta."""
    from ..models_elearning import TrainingElearningRispostaAperta as R

    risposta = R.objects.create(
        corso=corso, nome=nome, cognome=cognome, matricola=(matricola or "")[:40], partecipazione=partecipazione,
        punteggio_pct=esito["punteggio_pct"],
        n_corrette=esito["n_corrette"], n_totali=esito["n_totali"], superato=esito["superato"],
        risposte_json={"risposte": esito["risposte"]}, versione_corso=corso.versione or "",
        avviato_il=avviato_il, ip=ip or None,
        ua_hash=hashlib.sha256((user_agent or "").encode()).hexdigest() if user_agent else "",
    )
    if partecipazione is not None and partecipazione.legacy_anagrafica_id:
        legacy_id, nota = partecipazione.legacy_anagrafica_id, ""
    else:
        legacy_id, nota = abbinamento_con_matricola(nome, cognome, matricola,
                                                    reparto=getattr(partecipazione, "reparto", ""))
    if partecipazione is not None and esito.get("superato"):
        type(partecipazione).objects.filter(pk=partecipazione.pk).update(completata_il=timezone.now())
    if legacy_id:
        abbina(risposta, legacy_id, user=None, stato=R.AUTO)
        risposta.refresh_from_db()
    else:
        R.objects.filter(pk=risposta.pk).update(nota=nota[:300])
        risposta.nota = nota[:300]
    return risposta
