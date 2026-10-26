"""Account di Active Directory via LDAP (sola lettura), abbinati all'anagrafica.

Lettura ``registro_ad`` (ogni 6 ore, «Esegui ora» in Impostazioni › Letture automatiche).
Usa la connessione LDAP del portale (``LDAP_SERVER``, account di servizio): nessuna
credenziale nuova. Per ogni account salva solo una fotografia (stato attuale): chi è,
se è abilitato, ultimo accesso, età della password, gruppi di amministratori di cui fa
parte (anche tramite gruppi annidati) e la persona dell'anagrafica a cui appartiene.

Da qui nascono le segnalazioni della pagina Account AD (ex dipendenti con l'account
attivo, amministratori senza nomina, password che non scadono…) e l'elenco degli
account privilegiati usato dal raccoglitore per riconoscere gli accessi degli
amministratori di sistema.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

GRUPPI_DA_CERCARE = (
    "Domain Admins", "Enterprise Admins", "Schema Admins", "Administrators", "Account Operators",
    "Backup Operators", "Server Operators", "Print Operators", "DnsAdmins", "Group Policy Creator Owners",
    "Key Admins", "Enterprise Key Admins", "ESX Admins",
)
UAC_DISABILITATO = 0x2
UAC_PASSWORD_NON_SCADE = 0x10000
INATTIVO_GIORNI = 90
KRBTGT_GIORNI = 180
ATTRIBUTI = ["sAMAccountName", "userPrincipalName", "displayName", "mail", "distinguishedName", "userAccountControl",
             "lastLogonTimestamp", "pwdLastSet", "whenCreated", "description"]


def configurato() -> bool:
    return bool(getattr(settings, "LDAP_SERVER", "") and getattr(settings, "LDAP_SERVICE_USER", "")
                and getattr(settings, "LDAP_BASE_DN", ""))


def _connessione():
    from ldap3 import NTLM, SIMPLE, Connection

    from core.ldap_conn import build_ldap_server, ldap_receive_timeout

    utente = settings.LDAP_SERVICE_USER
    tentativi = [(utente, NTLM)] if "\\" in utente else [(utente, SIMPLE)]
    if "\\" not in utente and "@" not in utente:
        tentativi = []
        if settings.LDAP_UPN_SUFFIX:
            tentativi.append((f"{utente}@{settings.LDAP_UPN_SUFFIX}", SIMPLE))
        if settings.LDAP_DOMAIN:
            tentativi.append((f"{settings.LDAP_DOMAIN}\\{utente}", NTLM))
        tentativi.append((utente, SIMPLE))
    server = build_ldap_server(settings.LDAP_SERVER, int(getattr(settings, "LDAP_TIMEOUT", 5) or 5))
    ultimo = None
    for nome, metodo in tentativi:
        conn = Connection(server, user=nome, password=settings.LDAP_SERVICE_PASSWORD, authentication=metodo,
                          auto_bind=False, auto_referrals=False, raise_exceptions=False,
                          receive_timeout=ldap_receive_timeout(), read_only=True)
        if conn.bind():
            return conn
        ultimo = conn.result
    raise RuntimeError(f"Accesso LDAP non riuscito con l'account di servizio del portale: {ultimo}")


def _cerca(conn, filtro: str, attributi: list[str], base: str = "") -> list[dict]:
    righe = conn.extend.standard.paged_search(
        search_base=base or settings.LDAP_BASE_DN, search_filter=filtro, attributes=attributi,
        paged_size=int(getattr(settings, "LDAP_SYNC_PAGE_SIZE", 500) or 500), generator=True,
    )
    return [dict(r.get("attributes") or {}) for r in righe if r.get("type") == "searchResEntry"]


def _valore(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def data_ad(v) -> datetime | None:
    """Date di AD: ldap3 le dà già come datetime, oppure come FILETIME (100 ns dal 1601)."""
    v = _valore(v)
    if v in (None, "", 0, "0"):
        return None
    if isinstance(v, datetime):
        if v.year <= 1601:
            return None
        return v if timezone.is_aware(v) else v.replace(tzinfo=dt_timezone.utc)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n <= 0 or n >= 0x7FFFFFFFFFFFFFFF:
        return None
    return datetime(1601, 1, 1, tzinfo=dt_timezone.utc) + timedelta(microseconds=n // 10)


def _escape(dn: str) -> str:
    from ldap3.utils.conv import escape_filter_chars

    return escape_filter_chars(dn)


def leggi() -> tuple[list[dict], dict[str, list[str]]]:
    """(utenti, {sam minuscolo: [gruppi privilegiati]}) letti da AD."""
    conn = _connessione()
    try:
        utenti = _cerca(conn, "(&(objectCategory=person)(objectClass=user))", ATTRIBUTI)
        gruppi: dict[str, list[str]] = {}
        nomi = "".join(f"(cn={_escape(g)})" for g in GRUPPI_DA_CERCARE)
        for g in _cerca(conn, f"(&(objectClass=group)(|{nomi}))", ["cn", "distinguishedName"]):
            dn, cn = _valore(g.get("distinguishedName")), _valore(g.get("cn"))
            if not dn:
                continue
            # Regola LDAP_MATCHING_RULE_IN_CHAIN: membri anche tramite gruppi annidati.
            for m in _cerca(conn, f"(&(objectCategory=person)(objectClass=user)(memberOf:1.2.840.113556.1.4.1941:={_escape(dn)}))",
                            ["sAMAccountName"]):
                sam = str(_valore(m.get("sAMAccountName")) or "").lower()
                if sam:
                    gruppi.setdefault(sam, []).append(str(cn))
        return utenti, gruppi
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def _persone():
    from core.account_m365 import _indice, _persone

    return _indice(_persone())


def _trova(u: dict, indice: dict) -> dict | None:
    for campo in ("mail", "userPrincipalName"):
        v = str(_valore(u.get(campo)) or "").strip().lower()
        if v and v in indice:
            return indice[v]
    sam = str(_valore(u.get("sAMAccountName")) or "").strip().lower()
    return indice.get(f"login:{sam}") if sam else None


def applica(utenti: list[dict], gruppi: dict[str, list[str]], indice: dict, *, ora: datetime | None = None) -> dict:
    """Aggiorna la fotografia degli account. Funzione separata dalla lettura per poterla provare."""
    from .models import AccountAD

    ora = ora or timezone.now()
    oggi = timezone.localdate(ora)
    esistenti = {a.sam.lower(): a for a in AccountAD.objects.all()}
    visti = set()
    esito = {"account": 0, "nuovi": 0, "privilegiati": 0, "cessati_attivi": 0}
    for u in utenti:
        sam = str(_valore(u.get("sAMAccountName")) or "").strip()
        if not sam:
            continue
        chiave = sam.lower()
        visti.add(chiave)
        uac = int(_valore(u.get("userAccountControl")) or 0)
        a = esistenti.get(chiave) or AccountAD(sam=sam)
        if a.pk is None:
            esito["nuovi"] += 1
        a.upn = str(_valore(u.get("userPrincipalName")) or "")[:255]
        a.nome = str(_valore(u.get("displayName")) or "")[:255]
        a.email = str(_valore(u.get("mail")) or "")[:255]
        a.dn = str(_valore(u.get("distinguishedName")) or "")[:500]
        a.abilitato = not (uac & UAC_DISABILITATO)
        a.password_non_scade = bool(uac & UAC_PASSWORD_NON_SCADE)
        a.ultimo_accesso = data_ad(u.get("lastLogonTimestamp"))
        a.password_cambiata_il = data_ad(u.get("pwdLastSet"))
        a.creato_ad_il = data_ad(u.get("whenCreated"))
        a.gruppi_privilegiati = sorted(set(gruppi.get(chiave, [])))
        if not a.abbinamento_manuale:
            p = _trova(u, indice)
            a.anagrafica_id = p["id"] if p else None
            a.anagrafica_nome = (p["nome"] if p else "")[:255]
            if p and a.tipo == AccountAD.TIPO_SCONOSCIUTO:
                a.tipo = AccountAD.TIPO_PERSONA
            cessato = p.get("cessato_il") if p else None
            a.persona_cessata = bool(cessato and cessato <= oggi)
        a.visto_il, a.sparito_il = ora, None
        a.save()
        esito["account"] += 1
        esito["privilegiati"] += int(bool(a.gruppi_privilegiati))
        esito["cessati_attivi"] += int(a.persona_cessata and a.abilitato)
    for chiave, a in esistenti.items():
        if chiave not in visti and a.sparito_il is None:
            AccountAD.objects.filter(pk=a.pk).update(sparito_il=ora)
    return esito


def sincronizza() -> dict:
    if not configurato():
        return {"attivo": False, "skipped": "Connessione LDAP del portale non configurata (Setup Wizard › LDAP)."}
    utenti, gruppi = leggi()
    esito = applica(utenti, gruppi, _persone())
    _segnala_cessati()
    from .models import FonteLog

    for fonte in FonteLog.objects.filter(tipo=FonteLog.TIPO_DOMINIO, attiva=True):
        try:
            esito[f"pc_{fonte.pk}"] = aggiorna_postazioni(fonte)
        except Exception as exc:  # noqa: BLE001 - una fonte non blocca le altre
            logger.exception("Registro accessi: elenco dei PC di %s non aggiornato", fonte)
            esito[f"pc_{fonte.pk}"] = {"errore": str(exc)[:300]}
    return esito


# ── PC del dominio (fonti «Tutti i PC del dominio») ──────────────────────────

PC_NON_USATO_GIORNI = 60
UAC_FILTRO_ATTIVI = "(!(userAccountControl:1.2.840.113556.1.4.803:=2))"


def leggi_pc(base: str = "") -> list[dict]:
    """Computer Windows abilitati del dominio (o dell'unità organizzativa indicata)."""
    conn = _connessione()
    try:
        return _cerca(conn, f"(&(objectCategory=computer){UAC_FILTRO_ATTIVI}(operatingSystem=Windows*))",
                      ["name", "dNSHostName", "operatingSystem", "lastLogonTimestamp"], base=base)
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def applica_pc(fonte, computer: list[dict], *, ora: datetime | None = None) -> dict:
    """Aggiorna l'elenco dei PC della fonte. Restano fuori i server già letti come fonte a sé e i PC non usati da 60 giorni.

    I PC spariti da AD o non più usati restano in elenco (con i loro segnalibri) ma non si leggono più.
    """
    from .models import FonteLog, Postazione

    ora = ora or timezone.now()
    gia_fonti = {h.strip().split(".")[0].lower() for h in FonteLog.objects.filter(
        tipo=FonteLog.TIPO_WINDOWS, attiva=True).values_list("host", flat=True) if h.strip()}
    esistenti = {p.nome.lower(): p for p in Postazione.objects.filter(fonte_id=fonte.pk)}
    visti, esito = set(), {"pc": 0, "nuovi": 0, "non_usati": 0, "gia_fonti": 0}
    limite = ora - timedelta(days=PC_NON_USATO_GIORNI)
    for c in computer:
        nome = str(_valore(c.get("name")) or "").strip()
        if not nome:
            continue
        chiave = nome.lower()
        if chiave in gia_fonti:
            esito["gia_fonti"] += 1
            continue
        ultimo = data_ad(c.get("lastLogonTimestamp"))
        usato = ultimo is None or ultimo >= limite
        p = esistenti.get(chiave) or Postazione(fonte_id=fonte.pk, nome=nome[:120])
        if p.pk is None:
            if not usato:
                esito["non_usati"] += 1
                continue
            esito["nuovi"] += 1
        p.indirizzo = str(_valore(c.get("dNSHostName")) or "")[:255]
        p.sistema = str(_valore(c.get("operatingSystem")) or "")[:120]
        p.ultimo_accesso_ad = ultimo
        p.in_ad = usato
        p.save()
        visti.add(chiave)
        esito["pc"] += int(usato)
        esito["non_usati"] += int(not usato)
    for chiave, p in esistenti.items():
        if chiave not in visti and p.in_ad:
            Postazione.objects.filter(pk=p.pk).update(in_ad=False)
    return esito


def aggiorna_postazioni(fonte) -> dict:
    if not configurato():
        raise RuntimeError("Connessione LDAP del portale non configurata (Setup Wizard › LDAP).")
    return applica_pc(fonte, leggi_pc((fonte.ou_pc or "").strip()))


def _segnala_cessati() -> None:
    """Account AD abilitato di una persona cessata → evento del SOC (una volta per account)."""
    from security.models import Severity
    from security.services import soc_settings

    from .ciclo import _evento_soc, _soc_source
    from .models import AccountAD

    if not (soc_settings.value("registro.alert.attivo") and soc_settings.value("registro.alert.ad_cessati")):
        return
    source = _soc_source()
    nuovi = 0
    for a in AccountAD.objects.filter(persona_cessata=True, abilitato=True, sparito_il__isnull=True):
        nuovi += _evento_soc(source, "ad_cessato", f"Account di Active Directory ancora attivo di un ex dipendente: "
                             f"{a.sam} ({a.anagrafica_nome})", Severity.HIGH, f"adcess|{a.sam.lower()}", timezone.now(),
                             {"account": a.sam, "persona": a.anagrafica_nome})
    if nuovi:
        from security.services.rule_engine import evaluate_security_rules

        evaluate_security_rules()


# ── Segnalazioni per la pagina ────────────────────────────────────────────────


def segnalazioni(ora: datetime | None = None) -> list[dict]:
    """Cosa c'è da sistemare negli account, in ordine di importanza. Ogni voce: titolo, perché, account."""
    from .models import AccountAD, AmministratoreSistema

    ora = ora or timezone.now()
    attivi = list(AccountAD.objects.filter(sparito_il__isnull=True))
    abilitati = [a for a in attivi if a.abilitato]
    nominati = set()
    for ads in AmministratoreSistema.objects.all():
        if ads.attivo:
            nominati.update(x.split("\\")[-1].split("@")[0].lower() for x in ads.lista_account())
    inattivo = ora - timedelta(days=INATTIVO_GIORNI)
    voci = [
        ("critical", "Ex dipendenti con l'account ancora attivo",
         "La persona risulta cessata in anagrafica ma può ancora entrare in rete: disattivare l'account.",
         [a for a in abilitati if a.persona_cessata]),
        ("high", "Amministratori senza nomina",
         "L'account è in un gruppo di amministratori ma non compare nell'elenco degli amministratori di sistema: "
         "aggiungere la nomina o togliere l'account dal gruppo.",
         [a for a in abilitati if a.gruppi_privilegiati and a.sam.lower() not in nominati and a.sam.lower() != "krbtgt"]),
        ("warning", "Account senza una persona",
         "Non è stato possibile abbinarlo all'anagrafica: indicare la persona o segnarlo come account di servizio con un responsabile.",
         [a for a in abilitati if a.tipo == AccountAD.TIPO_SCONOSCIUTO and not a.anagrafica_id]),
        ("warning", "Account di servizio senza responsabile",
         "Ogni account di servizio deve avere una persona che ne risponde.",
         [a for a in abilitati if a.tipo == AccountAD.TIPO_SERVIZIO and not a.responsabile]),
        ("warning", f"Account non usati da oltre {INATTIVO_GIORNI} giorni",
         "Abilitati ma senza accessi recenti: valutare se disattivarli.",
         [a for a in abilitati if a.tipo != AccountAD.TIPO_SERVIZIO and a.ultimo_accesso and a.ultimo_accesso < inattivo]),
        ("info", "Password che non scadono (persone)",
         "Per gli account delle persone la password dovrebbe avere una scadenza o un secondo fattore.",
         [a for a in abilitati if a.password_non_scade and a.tipo == AccountAD.TIPO_PERSONA]),
    ]
    krbtgt = next((a for a in attivi if a.sam.lower() == "krbtgt"), None)
    if krbtgt and krbtgt.password_cambiata_il and krbtgt.password_cambiata_il < ora - timedelta(days=KRBTGT_GIORNI):
        voci.append(("info", f"Password di krbtgt più vecchia di {KRBTGT_GIORNI} giorni",
                     "Cambiarla due volte (a distanza di qualche ora) riduce il rischio di ticket Kerberos falsificati.", [krbtgt]))
    return [{"tono": t, "titolo": ti, "perche": pe, "account": acc} for t, ti, pe, acc in voci if acc]
