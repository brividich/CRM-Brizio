"""Firma su portale con le immagini del Registro timbri.

Regole (MT CN 08 §7.2.1: redige il responsabile di processo, approva RDD,
delegato del CEO):

- un documento si invia in firma con una copia congelata del contenuto e la sua
  impronta SHA-256; finché è in firma il contenuto non cambia;
- le caselle si firmano in ordine; una casella la firma chi invia («mittente») o
  chi ricopre oggi il ruolo indicato (catalogo ruoli dell'anagrafica);
- ognuno firma **solo con le proprie immagini** del Registro timbri: record
  attivo, non sospeso, non archiviato, non ritirato. Le immagini degli altri non
  sono mai selezionabili;
- la firma si conferma con il codice dell'app di autenticazione (chi ha la 2FA
  con app) o con la password;
- le immagini usate vengono copiate nella casella; dopo l'ultima firma il
  documento è chiuso. Chi lo usa (es. l'organigramma) riceve ``al_firmato``.

Questo non è una firma digitale qualificata (PAdES): è una firma interna con
traccia nel portale (chi, quando, da dove, impronta del contenuto).
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Callable

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import CasellaFirma, DocumentoFirma, ImpostazioneFirma, OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine

VARIANTI_BASE = ("FIRMA", "TIMBRO", "SIGLA")
MAX_CASELLE = 4


class FirmaNegata(Exception):
    """Errore da mostrare all'utente così com'è."""


# ── tipi di documento ────────────────────────────────────────────────────────

@dataclass
class TipoDocumento:
    nome: str
    caselle_di_serie: list[dict]
    #: (documento, user) → None; chiamato dentro la transazione dell'ultima firma.
    al_firmato: Callable | None = None


_TIPI: dict[str, TipoDocumento] = {}


def registra_tipo(chiave: str, tipo: TipoDocumento) -> None:
    _TIPI[chiave] = tipo


def tipo(chiave: str) -> TipoDocumento:
    if chiave not in _TIPI:
        # I tipi si registrano all'import del modulo che li usa.
        if chiave == "organigramma_ufficiale":
            import anagrafica.services.organigramma_firma  # noqa: F401
        elif chiave == "skill_matrix_mod187":
            import anagrafica.services.skillmatrix_emissioni  # noqa: F401
    return _TIPI[chiave]


# ── impostazioni ─────────────────────────────────────────────────────────────

def _pulisci_caselle(caselle) -> list[dict]:
    out = []
    for c in (caselle or [])[:MAX_CASELLE]:
        if not isinstance(c, dict):
            continue
        etichetta = " ".join(str(c.get("etichetta") or "").split())[:60]
        if not etichetta:
            continue
        varianti = [v for v in (c.get("varianti") or []) if v in VARIANTI_BASE] or ["FIRMA"]
        ruolo = c.get("ruolo")
        ruolo = int(ruolo) if str(ruolo or "").isdigit() else None
        out.append({
            "etichetta": etichetta,
            "mittente": bool(c.get("mittente")) and not ruolo,
            "ruolo": ruolo,
            "ruolo_sigla": " ".join(str(c.get("ruolo_sigla") or "").split())[:20],
            "varianti": varianti,
        })
    return out


def impostazione(chiave: str) -> dict:
    """{"attiva": bool, "caselle": [...]} per il tipo: quelle salvate o quelle di serie."""
    riga = ImpostazioneFirma.objects.filter(tipo=chiave).first()
    if riga is None:
        return {"attiva": True, "caselle": _pulisci_caselle(tipo(chiave).caselle_di_serie), "salvata": False}
    caselle = _pulisci_caselle(riga.caselle) or _pulisci_caselle(tipo(chiave).caselle_di_serie)
    return {"attiva": riga.attiva, "caselle": caselle, "salvata": True}


def salva_impostazione(chiave: str, *, attiva: bool, caselle: list[dict], user) -> dict:
    pulite = _pulisci_caselle(caselle)
    if attiva and not pulite:
        raise FirmaNegata("Serve almeno una casella di firma.")
    if attiva and not any(c["ruolo"] or c["ruolo_sigla"] for c in pulite):
        raise FirmaNegata("Serve almeno una casella firmata da un ruolo (es. RDD).")
    ImpostazioneFirma.objects.update_or_create(
        tipo=chiave,
        defaults={"attiva": attiva, "caselle": pulite,
                  "aggiornata_da": user if getattr(user, "is_authenticated", False) else None},
    )
    return impostazione(chiave)


def _ruolo_della_casella(c: dict):
    from anagrafica.models import RuoloOperativo

    if c.get("ruolo"):
        return RuoloOperativo.objects.filter(pk=c["ruolo"], is_active=True).first()
    if c.get("ruolo_sigla"):
        return (RuoloOperativo.objects.filter(is_active=True, sigla__iexact=c["ruolo_sigla"]).order_by("pk").first())
    return None


# ── chi firma e con cosa ─────────────────────────────────────────────────────

def utenti_del_ruolo(ruolo) -> list:
    if ruolo is None:
        return []
    from core.operational_roles import get_users_for_role

    return list(get_users_for_role(ruolo.pk))


def puo_firmare_casella(user, casella: CasellaFirma) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if casella.mittente:
        return casella.documento.creato_da_id == user.pk
    if casella.ruolo_id is None:
        return False
    return any(u.pk == user.pk for u in utenti_del_ruolo(casella.ruolo))


def immagini_proprie(user) -> dict[str, RegistroTimbroImmagine]:
    """Le immagini utilizzabili dell'utente, per variante (la più recente fra i record validi)."""
    from core.operational_roles import get_legacy_anagrafica_id

    lid = get_legacy_anagrafica_id(user)
    if not lid:
        return {}
    oggi = timezone.localdate()
    operatori = OperatoreTimbri.objects.filter(legacy_anagrafica_id=lid).values_list("pk", flat=True)
    registri = RegistroTimbro.objects.filter(
        operatore_id__in=list(operatori), is_attivo=True, is_archived=False, is_sospeso=False,
    ).filter(Q(data_ritiro__isnull=True) | Q(data_ritiro__gt=oggi))
    out: dict[str, RegistroTimbroImmagine] = {}
    for img in (RegistroTimbroImmagine.objects.filter(registro__in=registri)
                .select_related("registro", "registro__operatore")
                .order_by("-registro__data_consegna", "-registro__updated_at", "-id")):
        out.setdefault(img.variante, img)
    return out


def opzioni(user, casella: CasellaFirma) -> list[dict]:
    """Cosa può mettere l'utente nella casella: Firma, Timbro, Timbro + firma, Sigla."""
    proprie = immagini_proprie(user)
    ammesse = casella.varianti_ammesse
    out = []
    for chiave, etichetta, servono in (
        ("FIRMA", "Firma", ("FIRMA",)),
        ("TIMBRO_FIRMA", "Timbro + firma", ("TIMBRO", "FIRMA")),
        ("TIMBRO", "Timbro", ("TIMBRO",)),
        ("SIGLA", "Sigla", ("SIGLA",)),
    ):
        if not all(v in ammesse for v in servono):
            continue
        immagini = [proprie.get(v) for v in servono]
        out.append({
            "chiave": chiave, "etichetta": etichetta,
            "disponibile": all(immagini),
            "immagini": [i for i in immagini if i],
            "codice": next((i.registro.codice_timbro for i in immagini if i and i.registro.codice_timbro), ""),
        })
    return out


def nome_utente(user) -> str:
    from core.naming import nome_completo

    nome = nome_completo(getattr(user, "last_name", "") or "", getattr(user, "first_name", "") or "")
    return " ".join((nome or "").split()) or user.get_username()


# ── conferma dell'identità ──────────────────────────────────────────────────

def usa_totp(user) -> bool:
    tf = getattr(user, "twofa", None)
    try:
        return bool(tf and tf.is_active and tf.method == "totp" and tf.totp_confirmed and tf.totp_secret_enc)
    except Exception:
        return False


def conferma_identita(request, user, segreto: str) -> str:
    """Verifica codice dell'app (se l'utente ha la 2FA con app) o password. Ritorna il metodo usato."""
    segreto = (segreto or "").strip()
    if not segreto:
        raise FirmaNegata("Inserisci " + ("il codice dell'app di autenticazione." if usa_totp(user) else "la password."))
    if usa_totp(user):
        from twofa.utils import decrypt_totp_secret, verify_totp_once

        if not verify_totp_once(user, decrypt_totp_secret(user.twofa.totp_secret_enc), segreto):
            raise FirmaNegata("Codice non valido o già usato: attendi il codice successivo.")
        return CasellaFirma.CONFERMA_TOTP
    from django.contrib.auth import authenticate

    verificato = authenticate(request, username=user.get_username(), password=segreto)
    if verificato is None or verificato.pk != user.pk:
        raise FirmaNegata("Password non corretta.")
    return CasellaFirma.CONFERMA_PASSWORD


# ── ciclo di vita ────────────────────────────────────────────────────────────

def calcola_impronta(chiave: str, oggetto_id: int, numero: int, contenuto: dict) -> str:
    testo = json.dumps({"tipo": chiave, "oggetto": oggetto_id, "numero": numero, "contenuto": contenuto},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def _nuovo_codice() -> str:
    for _ in range(20):
        raw = secrets.token_hex(4).upper()
        codice = f"{raw[:4]}-{raw[4:]}"
        if not DocumentoFirma.objects.filter(codice_verifica=codice).exists():
            return codice
    raise RuntimeError("Codice di verifica non generabile.")


def in_firma(chiave: str, oggetto_id: int) -> DocumentoFirma | None:
    return (DocumentoFirma.objects.filter(tipo=chiave, oggetto_id=oggetto_id, stato=DocumentoFirma.STATO_IN_FIRMA)
            .prefetch_related("caselle").first())


def firmato_per_esito(chiave: str, esito_id: int) -> DocumentoFirma | None:
    return (DocumentoFirma.objects.filter(tipo=chiave, esito_id=esito_id, stato=DocumentoFirma.STATO_FIRMATO)
            .prefetch_related("caselle").first())


def casella_corrente(doc: DocumentoFirma) -> CasellaFirma | None:
    return next((c for c in doc.caselle.all() if c.stato == CasellaFirma.STATO_ATTESA), None)


def notifica(user, tipo_notifica: str, messaggio: str, url: str) -> None:
    from core.notifiche import invia_notifica

    profilo = getattr(user, "profile", None)
    invia_notifica(getattr(profilo, "legacy_user_id", None), tipo_notifica, messaggio, url)


def avvisa_prossimi(doc: DocumentoFirma, url: str) -> None:
    casella = casella_corrente(doc)
    if casella is None:
        return
    destinatari = [doc.creato_da] if casella.mittente and doc.creato_da else utenti_del_ruolo(casella.ruolo)
    for u in destinatari:
        notifica(u, "firma_da_apporre", f"Da firmare ({casella.etichetta}): {doc.titolo}", url)


@transaction.atomic
def invia(chiave: str, *, oggetto_id: int, titolo: str, numero: int, contenuto: dict, nota: str, user) -> DocumentoFirma:
    """Crea il documento in firma con le caselle dell'impostazione del tipo."""
    if in_firma(chiave, oggetto_id) is not None:
        raise FirmaNegata("Questo documento è già in firma.")
    imp = impostazione(chiave)
    if not imp["attiva"]:
        raise FirmaNegata("La firma su portale è spenta per questo tipo di documento.")
    righe = []
    for i, c in enumerate(imp["caselle"], start=1):
        ruolo = None
        if not c["mittente"]:
            ruolo = _ruolo_della_casella(c)
            if ruolo is None:
                raise FirmaNegata(f"Casella «{c['etichetta']}»: il ruolo {c.get('ruolo_sigla') or ''} non esiste "
                                  "nel catalogo ruoli. Sistemalo nelle impostazioni delle firme.")
            if not utenti_del_ruolo(ruolo):
                raise FirmaNegata(f"Casella «{c['etichetta']}»: nessun utente del portale ricopre oggi il ruolo "
                                  f"«{ruolo.nome}». Assegna il ruolo in anagrafica prima di inviare in firma.")
        righe.append((i, c, ruolo))
    doc = DocumentoFirma.objects.create(
        tipo=chiave, oggetto_id=oggetto_id, titolo=titolo[:250], numero_revisione=numero,
        contenuto=contenuto, impronta=calcola_impronta(chiave, oggetto_id, numero, contenuto),
        codice_verifica=_nuovo_codice(), nota=(nota or "")[:2000],
        creato_da=user if getattr(user, "is_authenticated", False) else None,
    )
    for i, c, ruolo in righe:
        CasellaFirma.objects.create(
            documento=doc, ordine=i, etichetta=c["etichetta"], mittente=c["mittente"], ruolo=ruolo,
            ruolo_etichetta=(f"{ruolo.sigla} · {ruolo.nome}" if ruolo and ruolo.sigla else (ruolo.nome if ruolo else "")),
            varianti=",".join(c["varianti"]),
        )
    return doc


def _copia(img: RegistroTimbroImmagine | None, campo, nome: str) -> None:
    if img is None:
        return
    with img.image.open("rb") as fh:
        campo.save(nome, ContentFile(fh.read()), save=False)


@transaction.atomic
def firma(request, doc: DocumentoFirma, *, user, scelta: str, segreto: str, dichiarazione: bool) -> DocumentoFirma:
    doc = DocumentoFirma.objects.select_for_update().get(pk=doc.pk)
    if doc.stato != DocumentoFirma.STATO_IN_FIRMA:
        raise FirmaNegata("Il documento non è più in firma.")
    if calcola_impronta(doc.tipo, doc.oggetto_id, doc.numero_revisione, doc.contenuto) != doc.impronta:
        raise FirmaNegata("Il contenuto non corrisponde all'impronta registrata: firma bloccata.")
    casella = casella_corrente(doc)
    if casella is None:
        raise FirmaNegata("Non ci sono caselle da firmare.")
    if not puo_firmare_casella(user, casella):
        raise FirmaNegata(f"La casella «{casella.etichetta}» non la puoi firmare tu.")
    if any(c.firmata_da_id == user.pk for c in doc.caselle.all() if c.stato == CasellaFirma.STATO_FIRMATA):
        raise FirmaNegata("Hai già firmato un'altra casella di questo documento: serve un'altra persona.")
    if not dichiarazione:
        raise FirmaNegata("Spunta la dichiarazione di aver verificato il documento.")
    opz = next((o for o in opzioni(user, casella) if o["chiave"] == scelta), None)
    if opz is None or not opz["disponibile"]:
        raise FirmaNegata("Scegli una delle tue immagini del Registro timbri ammesse per questa casella.")
    metodo = conferma_identita(request, user, segreto)

    per_variante = {i.variante: i for i in opz["immagini"]}
    casella.firmata_da = user
    casella.nome_firmatario = per_variante[next(iter(per_variante))].registro.operatore.full_name or nome_utente(user)
    casella.firmata_il = timezone.now()
    casella.variante = scelta
    casella.registro = (per_variante.get("FIRMA") or per_variante.get("SIGLA") or per_variante.get("TIMBRO")).registro
    casella.codice_timbro = opz["codice"][:120]
    casella.conferma = metodo
    from twofa.utils import get_client_ip

    casella.ip = get_client_ip(request) or None
    casella.stato = CasellaFirma.STATO_FIRMATA
    casella.save()
    _copia(per_variante.get("FIRMA") or per_variante.get("SIGLA"), casella.immagine_firma, "firma.png")
    _copia(per_variante.get("TIMBRO"), casella.immagine_timbro, "timbro.png")
    casella.save(update_fields=["immagine_firma", "immagine_timbro"])

    doc = DocumentoFirma.objects.prefetch_related("caselle").get(pk=doc.pk)
    if casella_corrente(doc) is None:
        doc.stato = DocumentoFirma.STATO_FIRMATO
        doc.chiuso_il = timezone.now()
        doc.save(update_fields=["stato", "chiuso_il"])
        t = tipo(doc.tipo)
        if t.al_firmato:
            t.al_firmato(doc, user)
    return doc


@transaction.atomic
def respingi(doc: DocumentoFirma, *, user, motivo: str) -> DocumentoFirma:
    doc = DocumentoFirma.objects.select_for_update().get(pk=doc.pk)
    if doc.stato != DocumentoFirma.STATO_IN_FIRMA:
        raise FirmaNegata("Il documento non è più in firma.")
    casella = casella_corrente(doc)
    if casella is None or not puo_firmare_casella(user, casella) or casella.mittente:
        raise FirmaNegata("Può respingere solo chi deve firmare la casella in attesa.")
    motivo = " ".join((motivo or "").split())[:1000]
    if not motivo:
        raise FirmaNegata("Scrivi il motivo: chi ha inviato il documento lo leggerà.")
    casella.stato = CasellaFirma.STATO_RESPINTA
    casella.firmata_da = user
    casella.nome_firmatario = nome_utente(user)
    casella.firmata_il = timezone.now()
    casella.motivo = motivo
    casella.save()
    doc.stato = DocumentoFirma.STATO_RESPINTO
    doc.motivo = motivo
    doc.chiuso_il = timezone.now()
    doc.save(update_fields=["stato", "motivo", "chiuso_il"])
    return doc


@transaction.atomic
def ritira(doc: DocumentoFirma, *, user, motivo: str = "") -> DocumentoFirma:
    doc = DocumentoFirma.objects.select_for_update().get(pk=doc.pk)
    if doc.stato != DocumentoFirma.STATO_IN_FIRMA:
        raise FirmaNegata("Il documento non è più in firma.")
    doc.stato = DocumentoFirma.STATO_RITIRATO
    doc.motivo = " ".join((motivo or "").split())[:1000] or f"Ritirato da {nome_utente(user)}"
    doc.chiuso_il = timezone.now()
    doc.save(update_fields=["stato", "motivo", "chiuso_il"])
    return doc


def puo_vedere_immagine(user, casella: CasellaFirma, *, vede_documento: bool, gestisce: bool) -> bool:
    """Immagine della casella: firmata e documento visibile; in firma solo a chi è coinvolto."""
    if casella.stato != CasellaFirma.STATO_FIRMATA:
        return False
    doc = casella.documento
    if doc.stato == DocumentoFirma.STATO_FIRMATO:
        return vede_documento
    if doc.stato == DocumentoFirma.STATO_IN_FIRMA:
        return gestisce or doc.creato_da_id == user.pk or any(
            puo_firmare_casella(user, c) for c in doc.caselle.all())
    return gestisce
