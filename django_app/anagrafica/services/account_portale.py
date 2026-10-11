"""Account portale del nuovo dipendente (prompt 03, obiettivo B).

Tre cose, separate:

* ``cerca_utenti_portale``: utenti portale già esistenti con la **stessa email o lo stesso codice
  fiscale** (corrispondenza esatta, mai per prefisso o alias).
* ``cerca_ad``: ricerca in Active Directory **in sola lettura** (solo ``search``, mai add/modify)
  per email, UPN o nome+cognome, con gruppi e stato abilitato/disabilitato.
* ``valida_scelta`` / ``applica_scelta``: la scelta dell'operatore (collega AD, crea utente locale,
  collega utente portale esistente, nessun accesso) rivalidata lato server al submit.

Regole (finding A3/M2 dell'audit): collegamento AD solo per UPN/email esatti e solo ad account
abilitati e nei gruppi di ``LDAP_GROUP_ALLOWLIST``; un account privilegiato (superuser, staff o con
password Django utilizzabile) si collega solo con conferma esplicita di un superuser; ogni
collegamento o creazione finisce in audit. Il portale non crea né modifica account in AD.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.ldap_conn import build_ldap_server, ldap_receive_timeout
from core.legacy_models import AnagraficaDipendente, Ruolo, UtenteLegacy
from core.legacy_utils import _ldap_escape_filter, canonicalize_ldap_upn, is_legacy_admin, ldap_group_cns

logger = logging.getLogger(__name__)

SCELTA_AD = "ad"
SCELTA_LOCALE = "locale"
SCELTA_COLLEGA = "collega"
SCELTA_NESSUNO = "nessuno"
SCELTE = (SCELTA_AD, SCELTA_LOCALE, SCELTA_COLLEGA, SCELTA_NESSUNO)

AD_MANAGED = "*AD_MANAGED*"
UAC_ACCOUNTDISABLE = 0x2
MAX_RISULTATI_AD = 10
ATTRIBUTI_AD = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName", "memberOf", "userAccountControl"]


# ── Utenti portale esistenti ─────────────────────────────────────────────────

def _utenti_django_collegati(legacy_ids: list[int]) -> dict[int, object]:
    from core.models import Profile

    if not legacy_ids:
        return {}
    return {p.legacy_user_id: p.user for p in Profile.objects.filter(legacy_user_id__in=legacy_ids).select_related("user")}


def privilegio(user) -> str:
    """Motivo per cui un ``User`` Django è privilegiato, o stringa vuota."""
    if user is None:
        return ""
    if user.is_superuser:
        return "superuser"
    if user.is_staff:
        return "staff"
    if user.has_usable_password():
        return "password locale utilizzabile"
    return ""


def _privilegio_legacy(legacy: UtenteLegacy, django_user=None) -> str:
    User = get_user_model()
    if is_legacy_admin(legacy):
        return "amministratore del portale"
    motivo = privilegio(django_user)
    if motivo:
        return motivo
    login = (legacy.email or "").strip()
    if login:
        # Un User privilegiato omonimo senza Profile verrebbe agganciato dalla sync al primo login.
        for omonimo in User.objects.filter(email__iexact=login):
            motivo = privilegio(omonimo)
            if motivo:
                return motivo
    return ""


def _collegato_a(legacy_ids: list[int]) -> dict[int, int]:
    if not legacy_ids:
        return {}
    righe = AnagraficaDipendente.objects.filter(utente_id__in=legacy_ids).values_list("utente_id", "id")
    return {int(u): int(a) for u, a in righe}


def cerca_utenti_portale(*, email: str = "", codice_fiscale: str = "") -> list[dict]:
    """Utenti portale con la stessa email (login o notifica) o lo stesso codice fiscale."""
    from anagrafica.models import DipendenteAnagraficaCivile

    trovati: dict[int, set[str]] = {}
    email = (email or "").strip()
    if email and "@" in email:
        for uid in UtenteLegacy.objects.filter(email__iexact=email).values_list("id", flat=True):
            trovati.setdefault(int(uid), set()).add("email")
        User = get_user_model()
        from core.models import Profile

        django_ids = list(User.objects.filter(email__iexact=email).values_list("id", flat=True))
        for lid in Profile.objects.filter(user_id__in=django_ids).values_list("legacy_user_id", flat=True):
            trovati.setdefault(int(lid), set()).add("email")
    cf = (codice_fiscale or "").strip().upper()
    if len(cf) == 16:
        anag_ids = list(DipendenteAnagraficaCivile.objects.filter(codice_fiscale__iexact=cf).values_list("legacy_anagrafica_id", flat=True))
        for uid in AnagraficaDipendente.objects.filter(id__in=anag_ids, utente_id__isnull=False).values_list("utente_id", flat=True):
            trovati.setdefault(int(uid), set()).add("codice fiscale")
    if not trovati:
        return []
    ids = list(trovati)
    django_map = _utenti_django_collegati(ids)
    collegati = _collegato_a(ids)
    risultati = []
    for legacy in UtenteLegacy.objects.filter(id__in=ids).order_by("id"):
        risultati.append({
            "id": legacy.id,
            "nome": legacy.nome or "",
            "login": legacy.email or "",
            "attivo": bool(legacy.attivo),
            "ad": (legacy.password or "") == AD_MANAGED,
            "corrispondenza": sorted(trovati[legacy.id]),
            "privilegiato": _privilegio_legacy(legacy, django_map.get(legacy.id)),
            "collegato_a": collegati.get(legacy.id),
        })
    return risultati


# ── Active Directory (sola lettura) ──────────────────────────────────────────

@dataclass
class AccountAD:
    upn: str
    sam: str
    nome: str
    mail: str
    abilitato: bool
    gruppi: list[str] = field(default_factory=list)
    in_allowlist: bool = True


@dataclass
class EsitoAD:
    stato: str  # ok | non_configurato | irraggiungibile | errore
    messaggio: str = ""
    risultati: list[AccountAD] = field(default_factory=list)


def _allowlist() -> set[str]:
    return {str(v).strip().casefold() for v in (getattr(settings, "LDAP_GROUP_ALLOWLIST", []) or []) if str(v).strip()}


def _in_allowlist(gruppi: list[str]) -> bool:
    consentiti = _allowlist()
    return not consentiti or any(g.casefold() in consentiti for g in gruppi)


def _configurazione() -> dict | None:
    if not bool(getattr(settings, "LDAP_ENABLED", False)):
        return None
    conf = {
        "server": str(getattr(settings, "LDAP_SERVER", "") or "").strip(),
        "base": str(getattr(settings, "LDAP_BASE_DN", "") or "").strip(),
        "filtro": str(getattr(settings, "LDAP_USER_FILTER", "") or "").strip() or "(objectClass=user)",
        "utente": str(getattr(settings, "LDAP_SERVICE_USER", "") or "").strip(),
        "password": str(getattr(settings, "LDAP_SERVICE_PASSWORD", "") or "").strip(),
        "dominio": str(getattr(settings, "LDAP_DOMAIN", "") or "").strip(),
        "suffisso": str(getattr(settings, "LDAP_UPN_SUFFIX", "") or "").strip().lstrip("@"),
        "timeout": int(getattr(settings, "LDAP_TIMEOUT", 5) or 5),
    }
    if not (conf["server"] and conf["base"] and conf["utente"] and conf["password"]):
        return None
    return conf


def _connetti(conf: dict):
    """Bind con l'utente di servizio (stessi tentativi di ``resolve_ldap_identity``). Solo lettura."""
    from ldap3 import NTLM, SIMPLE, Connection

    utente = conf["utente"]
    if "\\" in utente:
        tentativi = [(utente, NTLM)]
    elif "@" in utente:
        tentativi = [(utente, SIMPLE)]
    else:
        tentativi = ([(f"{utente}@{conf['suffisso']}", SIMPLE)] if conf["suffisso"] else []) + [(utente, SIMPLE)]
        if conf["dominio"]:
            tentativi.append((f"{conf['dominio']}\\{utente}", NTLM))
    server = build_ldap_server(conf["server"], conf["timeout"])
    for bind_user, metodo in tentativi:
        conn = Connection(server, user=bind_user, password=conf["password"], authentication=metodo, auto_bind=False,
                          auto_referrals=False, raise_exceptions=False, receive_timeout=ldap_receive_timeout())
        if conn.bind():
            return conn
        try:
            conn.unbind()
        except Exception:
            pass
    return None


def _valore(entry: dict, chiave: str) -> str:
    v = entry.get(chiave)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v or "").strip()


def _account_da_entry(attrs: dict) -> AccountAD:
    try:
        uac = int(_valore(attrs, "userAccountControl") or 0)
    except ValueError:
        uac = 0
    gruppi = ldap_group_cns(attrs.get("memberOf") or [])
    nome = _valore(attrs, "displayName") or " ".join(p for p in (_valore(attrs, "givenName"), _valore(attrs, "sn")) if p)
    return AccountAD(upn=_valore(attrs, "userPrincipalName").lower(), sam=_valore(attrs, "sAMAccountName"), nome=nome,
                     mail=_valore(attrs, "mail").lower(), abilitato=not (uac & UAC_ACCOUNTDISABLE), gruppi=gruppi,
                     in_allowlist=_in_allowlist(gruppi))


def _filtro_ricerca(*, email: str, upn: str, nome: str, cognome: str) -> str:
    parti = []
    for valore in dict.fromkeys(v.strip().lower() for v in (email, upn) if v and "@" in v):
        esc = _ldap_escape_filter(valore)
        parti += [f"(userPrincipalName={esc})", f"(mail={esc})"]
    if nome.strip() and cognome.strip():
        parti.append(f"(&(givenName={_ldap_escape_filter(nome.strip())})(sn={_ldap_escape_filter(cognome.strip())}))")
    return "".join(parti)


def cerca_ad(*, email: str = "", upn: str = "", nome: str = "", cognome: str = "") -> EsitoAD:
    conf = _configurazione()
    if conf is None:
        return EsitoAD("non_configurato", "La ricerca in Active Directory non è configurata su questo portale.")
    filtro = _filtro_ricerca(email=email, upn=upn, nome=nome, cognome=cognome)
    if not filtro:
        return EsitoAD("ok", "Inserisci un'email o nome e cognome per cercare in Active Directory.")
    try:
        from ldap3.core.exceptions import LDAPException
    except Exception:
        return EsitoAD("non_configurato", "Libreria LDAP non disponibile sul server.")
    conn = None
    try:
        conn = _connetti(conf)
        if conn is None:
            return EsitoAD("errore", "Active Directory ha rifiutato l'utente di servizio: avvisa l'amministratore di sistema.")
        conn.search(search_base=conf["base"], search_filter=f"(&{conf['filtro']}(|{filtro}))", attributes=ATTRIBUTI_AD,
                    size_limit=MAX_RISULTATI_AD)
        risultati = [_account_da_entry(e.get("attributes") or {}) for e in (conn.response or []) if e.get("type") == "searchResEntry"]
        return EsitoAD("ok", "", risultati)
    except (LDAPException, socket.error, OSError, ValueError) as exc:
        logger.warning("cerca_ad: Active Directory non raggiungibile: %s", type(exc).__name__)
        return EsitoAD("irraggiungibile", "Active Directory non risponde (timeout o rete). Il dipendente si può creare "
                                          "comunque: l'account si collega dopo dal riquadro «Account portale» della scheda.")
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:
                pass


def verifica_account_ad(upn: str) -> tuple[AccountAD | None, str, bool]:
    """Ricontrolla lato server l'account AD scelto: (account, errore, ad_irraggiungibile)."""
    upn = (upn or "").strip().lower()
    if "@" not in upn:
        return None, "Seleziona un account AD dai risultati della ricerca.", False
    esito = cerca_ad(upn=upn)
    if esito.stato != "ok":
        return None, esito.messaggio, esito.stato == "irraggiungibile"
    esatti = [a for a in esito.risultati if upn in (a.upn, a.mail)]
    if not esatti:
        return None, f"Nessun account AD con UPN o email esattamente «{upn}».", False
    if len(esatti) > 1:
        return None, f"Più account AD corrispondono a «{upn}»: risultato ambiguo, collega a mano dopo verifica.", False
    account = esatti[0]
    if not account.abilitato:
        return None, f"L'account AD «{account.upn or upn}» è disabilitato.", False
    if not account.in_allowlist:
        return None, f"L'account AD «{account.upn or upn}» non è in nessun gruppo autorizzato all'accesso al portale (LDAP_GROUP_ALLOWLIST).", False
    return account, "", False


# ── Scelta dell'operatore ────────────────────────────────────────────────────

@dataclass
class SceltaAccount:
    tipo: str = SCELTA_NESSUNO
    upn: str = ""
    collega_id: int | None = None
    login: str = ""
    password: str = ""
    conferma_privilegiato: bool = False


def scelta_da_post(post) -> SceltaAccount:
    tipo = (post.get("account_scelta") or SCELTA_NESSUNO).strip()
    raw_id = (post.get("account_collega_id") or "").strip()
    return SceltaAccount(
        tipo=tipo if tipo in SCELTE else SCELTA_NESSUNO,
        upn=(post.get("account_ad_upn") or "").strip().lower(),
        collega_id=int(raw_id) if raw_id.isdigit() else None,
        login=(post.get("account_login") or "").strip(),
        password=post.get("account_password") or "",
        conferma_privilegiato=post.get("account_conferma_privilegiato") == "1",
    )


def _blocco_privilegio(request, legacy: UtenteLegacy, scelta: SceltaAccount) -> str:
    motivo = _privilegio_legacy(legacy, _utenti_django_collegati([legacy.id]).get(legacy.id))
    if not motivo:
        return ""
    if getattr(request.user, "is_superuser", False) and scelta.conferma_privilegiato:
        return ""
    return (f"L'utente portale «{legacy.email or legacy.nome}» è un account privilegiato ({motivo}): "
            "il collegamento richiede la conferma esplicita di un superuser.")


def _collegato_altrove(legacy_id: int, scheda_id: int | None) -> bool:
    """L'utente portale è già su una scheda diversa da ``scheda_id`` (None = scheda non ancora creata)."""
    altra = _collegato_a([legacy_id]).get(legacy_id)
    return bool(altra) and altra != scheda_id


def valida_scelta(request, scelta: SceltaAccount, *, email: str, codice_fiscale: str, attivo: bool,
                  scheda_id: int | None = None) -> list[str]:
    """Errori bloccanti prima di applicare la scelta.

    Senza ``scheda_id`` (wizard di creazione) l'AD irraggiungibile non blocca: il dipendente si crea e
    l'account si collega dopo. Con ``scheda_id`` (riquadro «Account portale» di una scheda esistente)
    la scheda stessa è esclusa dal controllo «già collegato» e l'AD irraggiungibile blocca.
    """
    da_scheda = scheda_id is not None
    if scelta.tipo == SCELTA_NESSUNO:
        return ["Scegli come collegare l'account portale."] if da_scheda else []
    if not attivo:
        if da_scheda:
            return ["Il dipendente non è attivo: riattivalo prima di collegare un account portale."]
        return ["Un dipendente inserito come non attivo non riceve un accesso al portale: scegli «Nessun accesso»."]
    if scelta.tipo == SCELTA_LOCALE:
        errori = []
        errore_login = _errore_login_locale(scelta.login)
        if errore_login:
            errori.append(errore_login)
        try:
            validate_password(scelta.password)
        except ValidationError as exc:
            errori.extend(exc.messages)
        return errori
    if scelta.tipo == SCELTA_COLLEGA:
        candidati = {r["id"]: r for r in cerca_utenti_portale(email=email, codice_fiscale=codice_fiscale)}
        if scelta.collega_id not in candidati:
            return ["Si può collegare solo un utente portale trovato con la stessa email o lo stesso codice fiscale."]
        if candidati[scelta.collega_id]["collegato_a"] not in (None, scheda_id):
            return ["Questo utente portale è già collegato a un'altra scheda dipendente."]
        legacy = UtenteLegacy.objects.get(pk=scelta.collega_id)
        blocco = _blocco_privilegio(request, legacy, scelta)
        return [blocco] if blocco else []
    # SCELTA_AD
    account, errore, irraggiungibile = verifica_account_ad(scelta.upn)
    if irraggiungibile:
        return ["Active Directory non risponde (timeout o rete): account non collegato, riprova più tardi."] if da_scheda else []
    if account is None:
        return [errore]
    esistente = UtenteLegacy.objects.filter(email__iexact=account.upn or scelta.upn).first()
    if esistente is not None:
        if _collegato_altrove(esistente.id, scheda_id):
            return ["L'utente portale di questo account AD è già collegato a un'altra scheda dipendente."]
        blocco = _blocco_privilegio(request, esistente, scelta)
        if blocco:
            return [blocco]
    return []


_LOGIN_LOCALE_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")


def _errore_login_locale(login: str) -> str:
    """Un utente locale non deve poter occupare un'identità AD: niente login a forma di email,
    niente omonimi tra utenti portale/Django e, con l'AD configurato, nessun account AD omonimo."""
    login = (login or "").strip().lower()
    if not login:
        return "Indica il nome utente (login) dell'utente locale."
    if not _LOGIN_LOCALE_RE.match(login):
        return ("Il login dell'utente locale usa solo lettere minuscole, cifre, punto, trattino e trattino basso "
                "(niente @: gli indirizzi email sono riservati agli account Active Directory).")
    User = get_user_model()
    if (UtenteLegacy.objects.filter(email__iexact=login).exists()
            or UtenteLegacy.objects.filter(email__istartswith=f"{login}@").exists()
            or User.objects.filter(username__iexact=login).exists()
            or User.objects.filter(email__istartswith=f"{login}@").exists()):
        return f"Esiste già un utente con login «{login}»: usa «Collega utente portale esistente» o scegli un altro login."
    if _configurazione() is not None:
        upn = canonicalize_ldap_upn(login)
        esito = cerca_ad(upn=upn if "@" in upn else "", nome="", cognome="")
        if esito.stato != "ok":
            return "Non è stato possibile verificare in Active Directory che il login sia libero: riprova più tardi o scegli «Nessun accesso»."
        if esito.risultati:
            return f"In Active Directory esiste già l'account «{upn}»: collega l'account AD invece di creare un utente locale."
    return ""


def _audit(request, azione: str, new_id: int, dettaglio: dict) -> None:
    from core.audit import log_action

    log_action(request, azione, "anagrafica", dettaglio, oggetto_tipo="dipendente", oggetto_id=str(new_id))


def _collega(new_id: int, legacy: UtenteLegacy) -> bool:
    """Collega solo se la scheda è libera e l'utente non è già su un'altra scheda (ricontrollato qui)."""
    if AnagraficaDipendente.objects.filter(utente_id=legacy.id).exclude(id=new_id).exists():
        return False
    return AnagraficaDipendente.objects.filter(id=new_id, utente_id__isnull=True).update(utente_id=legacy.id) == 1


def applica_scelta(request, new_id: int, scelta: SceltaAccount, *, nome_completo: str,
                   da_scheda: bool = False) -> tuple[str, str]:
    """Esegue la scelta: (livello messaggio, testo).

    ``new_id`` è la scheda appena creata dal wizard oppure, con ``da_scheda``, una scheda esistente
    ancora senza utente collegato (riquadro «Account portale» della scheda dipendente).
    """
    from werkzeug.security import generate_password_hash

    origine = "scheda" if da_scheda else "creazione"
    if scelta.tipo == SCELTA_NESSUNO:
        return "info", "Nessun accesso al portale: l'account si può collegare in seguito dal riquadro «Account portale» della scheda."
    # Scheda già collegata (doppio submit o modifica concorrente): niente utenti orfani.
    if AnagraficaDipendente.objects.filter(id=new_id, utente_id__isnull=False).exists():
        return "warning", "La scheda ha già un account portale collegato: scollegalo prima di collegarne un altro."
    if scelta.tipo == SCELTA_COLLEGA:
        legacy = UtenteLegacy.objects.get(pk=scelta.collega_id)
        if not _collega(new_id, legacy):
            return "warning", "Utente portale non collegato: nel frattempo è stato collegato a un'altra scheda."
        _audit(request, "ACCOUNT_PORTALE_COLLEGATO", new_id, {"utente_legacy_id": legacy.id, "modo": "esistente", "origine": origine,
                                                              "conferma_privilegiato": scelta.conferma_privilegiato})
        return "success", f"Collegato all'utente portale «{legacy.email or legacy.nome}»."
    ruolo = Ruolo.objects.filter(nome__iexact="utente").first()
    if scelta.tipo == SCELTA_LOCALE:
        legacy = UtenteLegacy.objects.create(nome=nome_completo, email=scelta.login, password=generate_password_hash(scelta.password),
                                             ruolo="utente", ruolo_id=ruolo.id if ruolo else None, attivo=True,
                                             deve_cambiare_password=True)
        if not _collega(new_id, legacy):
            return "warning", "Utente locale creato ma non collegato alla scheda: collegalo a mano."
        _audit(request, "ACCOUNT_PORTALE_CREATO", new_id, {"utente_legacy_id": legacy.id, "modo": "locale", "origine": origine,
                                                           "login": scelta.login})
        return "success", f"Creato l'utente locale «{scelta.login}»: al primo accesso dovrà cambiare la password."
    account, errore, irraggiungibile = verifica_account_ad(scelta.upn)
    if account is None:
        if irraggiungibile:
            if da_scheda:
                return "warning", "Active Directory non risponde: account non collegato, riprova più tardi."
            return "warning", ("Active Directory non risponde: dipendente creato senza account, collegalo dopo dal "
                               "riquadro «Account portale» della scheda.")
        return "warning", f"Account AD non collegato: {errore}"
    upn = account.upn or scelta.upn
    legacy = UtenteLegacy.objects.filter(email__iexact=upn).first()
    creato = legacy is None
    if creato:
        legacy = UtenteLegacy.objects.create(nome=nome_completo or account.nome, email=upn, password=AD_MANAGED, ruolo="utente",
                                             ruolo_id=ruolo.id if ruolo else None, attivo=True, deve_cambiare_password=False)
    elif _collegato_altrove(legacy.id, new_id) or _blocco_privilegio(request, legacy, scelta):
        return "warning", "Account AD non collegato: l'utente portale è già collegato o è privilegiato."
    if not _collega(new_id, legacy):
        return "warning", "Account AD non collegato: nel frattempo l'utente è stato collegato a un'altra scheda."
    _audit(request, "ACCOUNT_PORTALE_COLLEGATO", new_id, {"utente_legacy_id": legacy.id, "modo": "ad", "upn": upn, "origine": origine,
                                                          "utente_creato": creato, "conferma_privilegiato": scelta.conferma_privilegiato})
    return "success", f"Collegato all'account AD «{upn}»."


def scollega(request, scheda_id: int) -> tuple[str, str]:
    """Scollega l'utente portale dalla scheda (``utente_id = NULL``): l'utente non viene cancellato."""
    utente_id = AnagraficaDipendente.objects.filter(id=scheda_id).values_list("utente_id", flat=True).first()
    if not utente_id:
        return "info", "La scheda non ha un account portale collegato."
    legacy = UtenteLegacy.objects.filter(pk=utente_id).first()
    if AnagraficaDipendente.objects.filter(id=scheda_id, utente_id=utente_id).update(utente_id=None) != 1:
        return "warning", "Account non scollegato: la scheda è stata modificata nel frattempo, ricarica la pagina."
    _audit(request, "ACCOUNT_PORTALE_SCOLLEGATO", scheda_id, {"utente_legacy_id": int(utente_id), "origine": "scheda",
                                                             "login": (legacy.email if legacy else "") or ""})
    etichetta = (legacy.email or legacy.nome) if legacy else f"#{utente_id}"
    return "success", f"Utente portale «{etichetta}» scollegato dalla scheda: l'utente non è stato cancellato."
