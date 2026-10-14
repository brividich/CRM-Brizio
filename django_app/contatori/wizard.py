"""Motore dei wizard guidati del modulo Contatori e wizard con connessione SNMP.

Stato in sessione, una voce per wizard aperto (avanti/indietro senza perdere dati).
I campi segreti (community, chiavi v3) entrano in sessione solo cifrati con
``credential_crypto.cifra``. Nessun salvataggio a DB fino alla conferma, salvo la
bozza esplicita. Le chiamate SNMP avvengono sempre fuori da ``transaction.atomic``.

Ogni wizard dichiara: ``passi``, ``azioni`` (azione POST -> (passo, metodo)),
``blocco(chiave)`` (perche' non si puo' superare un passo), ``salva(bozza=...)``,
``riepilogo()`` e i testi/URL di fine. La view e' unica (``views_wizard``).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from . import errori_snmp
from .forms_wizard import (
    CAMPI_SEGRETI, TIPO_MFC, PassoApparatoForm, PassoConnessioneForm, PassoVerificaForm, valori_asset,
)
from .models import CommunitySNMP, DispositivoSNMP, ImpostazioniSNMP, Macchina, ProfiloSNMP, StatoSNMP

logger = logging.getLogger(__name__)

SESSIONE = "contatori_wizard"
MAX_APERTI = 5           # wizard aperti per sessione: i piu' vecchi vengono scartati
TEST_TIMEOUT = 3          # secondi per tentativo, 1 retry solo sul timeout
MAX_COLONNE_MAPPATURA = 40


@dataclass(frozen=True)
class Passo:
    chiave: str
    titolo: str
    descrizione: str
    form_class: type | None = None


class MotoreWizard:
    """Stato e navigazione; le sottoclassi definiscono ``tipo``, ``passi`` e la conferma."""
    tipo = ""
    titolo = ""
    passi: tuple[Passo, ...] = ()
    azioni: dict = {}
    consente_bozza = False
    memorizza_su_azione = False  # True: il form del passo si salva prima di eseguire l'azione

    def __init__(self, request, wid):
        self.request = request
        self.wid = str(wid)
        self.stato = request.session.get(SESSIONE, {}).get(self.wid)
        if not self.stato or self.stato.get("tipo") != self.tipo:
            raise KeyError(self.wid)
        self.ctx = self.stato.get("ctx", {})

    # --- ciclo di vita -----------------------------------------------------
    @classmethod
    def da_query(cls, get):
        """(iniziali, ctx) dalla query di avvio; ValueError se il contesto non e' valido."""
        return {}, {}

    @classmethod
    def avvia(cls, request, iniziali=None, ctx=None):
        aperti = request.session.get(SESSIONE, {})
        if len(aperti) >= MAX_APERTI:
            for vecchio in sorted(aperti, key=lambda k: aperti[k].get("creato", ""))[:len(aperti) - MAX_APERTI + 1]:
                aperti.pop(vecchio)
        wid = str(uuid.uuid4())
        aperti[wid] = {"tipo": cls.tipo, "passo": 0, "dati": iniziali or {}, "extra": {}, "ctx": ctx or {},
                       "creato": timezone.now().isoformat()}
        request.session[SESSIONE] = aperti
        return wid

    def _salva(self):
        aperti = self.request.session.get(SESSIONE, {})
        aperti[self.wid] = self.stato
        self.request.session[SESSIONE] = aperti
        self.request.session.modified = True

    def chiudi(self):
        aperti = self.request.session.get(SESSIONE, {})
        aperti.pop(self.wid, None)
        self.request.session[SESSIONE] = aperti

    # --- navigazione -------------------------------------------------------
    @property
    def indice(self):
        return self.stato["passo"]

    @property
    def passo(self):
        return self.passi[self.indice]

    def indice_di(self, chiave):
        return next(i for i, p in enumerate(self.passi) if p.chiave == chiave)

    def vai(self, indice):
        self.stato["passo"] = max(0, min(indice, len(self.passi) - 1))
        self._salva()

    def extra(self, chiave):
        return self.stato["extra"].get(chiave)

    def imposta_extra(self, chiave, valore):
        self.stato["extra"][chiave] = valore
        self._salva()

    def blocco(self, chiave):
        """Messaggio se il passo ``chiave`` non si puo' superare (oltre al form valido)."""
        return ""

    def puo_salvare_bozza(self):
        """Messaggio se la bozza non si puo' salvare ("" se si puo')."""
        return ""

    def indice_ammesso(self, fino_a=None):
        """Primo passo prima di ``fino_a`` con form non valido o bloccato (riconvalida server)."""
        for i, passo in enumerate(self.passi[:fino_a]):
            if passo.form_class is not None and self.form_valido(passo.chiave) is None:
                return i
            if self.blocco(passo.chiave):
                return i
        return None

    # --- dati dei passi ----------------------------------------------------
    def kwargs_form(self, chiave):
        return {}

    def dati(self, chiave):
        """Dati salvati del passo, con i segreti decifrati (solo in memoria)."""
        from .credential_crypto import decifra
        dati = dict(self.stato["dati"].get(chiave, {}))
        cifrati = dati.pop("_segreti", "")
        if cifrati:
            dati.update(json.loads(decifra(cifrati)))
        return dati

    def form(self, chiave, data=None):
        passo = self.passi[self.indice_di(chiave)]
        if passo.form_class is None:
            return None
        if data is None:
            # Modifiche non ancora valide lasciate tornando indietro hanno la precedenza.
            iniziali = {**self.dati(chiave), **self.stato.get("bozze", {}).get(chiave, {})}
            return passo.form_class(initial=iniziali, **self.kwargs_form(chiave))
        precedenti = self.dati(chiave)
        if (any(precedenti.get(n) for n in CAMPI_SEGRETI) and not data.get("community_salvata")
                and not data.get("usa_globale")):
            # PasswordInput non ripropone il valore: campo vuoto = mantieni quello gia' inserito.
            data = data.copy()
            for nome in CAMPI_SEGRETI:
                if not data.get(nome) and precedenti.get(nome):
                    data[nome] = precedenti[nome]
        return passo.form_class(data=data, **self.kwargs_form(chiave))

    def memorizza(self, chiave, form):
        """Salva i valori grezzi del form valido; i segreti solo cifrati."""
        from .credential_crypto import cifra
        precedenti = self.dati(chiave)
        # Credenziale scelta dal catalogo o globale: i segreti digitati prima si scartano.
        scelta_esplicita = bool(form.cleaned_data.get("community_salvata") or form.cleaned_data.get("usa_globale"))
        valori, segreti = {}, {}
        for nome in form.fields:
            valore = form[nome].value()
            if nome in CAMPI_SEGRETI:
                # PasswordInput non ripropone il valore: vuoto = mantieni il precedente.
                segreti[nome] = "" if scelta_esplicita else (valore or precedenti.get(nome, ""))
            else:
                valori[nome] = valore
        if any(segreti.values()):
            valori["_segreti"] = cifra(json.dumps(segreti))
        self.stato["dati"][chiave] = valori
        self.stato.setdefault("bozze", {}).pop(chiave, None)
        self._salva()

    def ricorda_bozza(self, chiave, form):
        """Valori non validi (mai i segreti) da riproporre quando si torna sul passo."""
        self.stato.setdefault("bozze", {})[chiave] = {
            nome: form[nome].value() for nome in form.fields if nome not in CAMPI_SEGRETI}
        self._salva()

    def form_valido(self, chiave):
        passo = self.passi[self.indice_di(chiave)]
        if passo.form_class is None or chiave not in self.stato["dati"]:
            return None
        form = self.form(chiave, data=self.dati(chiave))
        return form if form.is_valid() else None

    # --- da definire -------------------------------------------------------
    def contesto_passo(self, chiave):
        return {}

    def riepilogo(self):
        return []

    def url_annulla(self):
        return reverse("contatori:snmp_centrale")

    def salva(self, *, bozza):
        raise NotImplementedError

    def fine(self, obj, *, bozza):
        """(url, livello messaggio, testo, azione audit, dettaglio audit)."""
        raise NotImplementedError


# --- Wizard «Nuovo apparato»: MFC a contratto o dispositivo SNMP -----------------

CAMPI_MFC = ("a4_bn", "a3_bn", "a4_col", "a3_col")

# Slug storici: i link a «+ MFC» e «+ Dispositivo SNMP» aprono il wizard unico.
ALIAS_APPARATO = {"macchina": TIPO_MFC, "dispositivo": ""}


class WizardApparato(MotoreWizard):
    """Un solo wizard per MFC e dispositivi: apparato → connessione → verifica → conferma.

    Il tipo scelto al primo passo decide cosa nasce: una ``Macchina`` (MFC a contratto,
    servono i quattro contatori letti) o un ``DispositivoSNMP`` (salvabile anche in bozza).
    """
    tipo = "apparato"
    titolo = "Nuovo apparato"
    passi = (
        Passo("apparato", "Apparato", "Parti dall'asset del registro, poi scegli il tipo.", PassoApparatoForm),
        Passo("connessione", "Connessione", "Indirizzo, versione SNMP e credenziali.", PassoConnessioneForm),
        Passo("verifica", "Verifica", "Il portale legge identità, modello e valori. Nessuna scrittura "
                                      "sull'apparato.", PassoVerificaForm),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )
    azioni = {"verifica": ("verifica", "esegui_verifica"), "collega": ("riepilogo", "collega_proposta")}
    memorizza_su_azione = True

    @classmethod
    def da_query(cls, get):
        """Precompilazione da Discovery, Stampanti MFC o scheda asset: valori grezzi, validati dai form."""
        apparato = {}
        if get.get("tipo_apparato"):
            apparato["tipo_apparato"] = get["tipo_apparato"][:20]
        for campo, limite in (("nome", 100), ("matricola", 40)):
            if get.get(campo):
                apparato[campo] = get[campo][:limite]
        if (get.get("asset") or "").isdigit():
            apparato["asset"] = get["asset"]
        rete = {k: get[k][:253] for k in ("host", "porta", "versione") if get.get(k)}
        if (get.get("community_id") or "").isdigit():
            rete["community_salvata"] = get["community_id"]
        # Precompilati come bozze: i passi si convalidano solo quando l'utente li conferma.
        bozze = {}
        if apparato:
            bozze["apparato"] = apparato
        if rete:
            bozze["connessione"] = {"porta": "161", "versione": "v2c", **rete}
        return {}, {"bozze": bozze} if bozze else {}

    @classmethod
    def avvia(cls, request, iniziali=None, ctx=None):
        bozze = (ctx or {}).pop("bozze", None)
        wid = super().avvia(request, iniziali, ctx)
        if bozze:
            aperti = request.session[SESSIONE]
            aperti[wid]["bozze"] = bozze
            request.session[SESSIONE] = aperti
        return wid

    # --- dati risolti --------------------------------------------------------
    def _apparato(self):
        form = self.form_valido("apparato")
        return form.cleaned_data if form is not None else {}

    def mfc(self):
        tipo = (self._apparato().get("tipo_apparato") or self.dati("apparato").get("tipo_apparato")
                or self.stato.get("bozze", {}).get("apparato", {}).get("tipo_apparato"))
        return tipo == TIPO_MFC

    @property
    def consente_bozza(self):
        return not self.mfc()

    def puo_salvare_bozza(self):
        if self.mfc():
            return "Una MFC a contratto non si salva in bozza: servono i quattro contatori letti."
        if self.form_valido("apparato") is None or self.form_valido("connessione") is None:
            return "Per salvare una bozza completa almeno «Apparato» e «Connessione»."
        return ""

    def kwargs_form(self, chiave):
        if chiave == "connessione":
            return {"globale_disponibile": bool(ImpostazioniSNMP.get_solo().community)}
        if chiave == "verifica":
            return {"solo_stampanti": self.mfc()}
        return {}

    def form(self, chiave, data=None):
        form = super().form(chiave, data)
        if chiave == "connessione" and form is not None and not form.is_bound and not form.initial.get("host"):
            host = valori_asset(self._apparato().get("asset")).get("host")
            if host:
                form.initial["host"] = host
        return form

    def memorizza(self, chiave, form):
        super().memorizza(chiave, form)
        if chiave == "connessione":
            # Si salva l'IP gia' risolto: niente DNS a ogni rivalidazione e firma della verifica stabile.
            self.stato["dati"]["connessione"]["host"] = form.cleaned_data["host"]
            self._salva()

    def parametri(self):
        """(host, porta, versione, segreto) dal passo connessione; segreto mai salvato in chiaro."""
        from .credential_crypto import decifra
        conn = self.form_valido("connessione")
        if conn is None:
            return None
        salvata = conn.cleaned_data.get("community_salvata")
        if conn._segreto_inline:
            segreto = conn._segreto_inline
        elif salvata is not None:
            segreto = decifra(salvata.segreto_cifrato)
        else:
            segreto = ImpostazioniSNMP.get_solo().community
        return conn.cleaned_data["host"], conn.cleaned_data["porta"], conn.cleaned_data["versione"], segreto

    def firma(self):
        """Impronta di rete+credenziali: se cambiano dopo la verifica, va rifatta."""
        parametri = self.parametri()
        if parametri is None:
            return ""
        return salted_hmac("contatori.wizard.test", "|".join(map(str, parametri))).hexdigest()

    def test_valido(self):
        esito = self.extra("test") or {}
        return bool(esito.get("ok")) and esito.get("firma") == self.firma() != ""

    def profilo_scelto(self):
        form = self.form_valido("verifica")
        return form.cleaned_data.get("profilo") if form is not None else None

    @staticmethod
    def _contatori_mancanti(profilo):
        presenti = set(profilo.colonne.filter(attiva=True).exclude(contatore_mfc="")
                       .values_list("contatore_mfc", flat=True))
        return [c for c in CAMPI_MFC if c not in presenti]

    def profilo(self):
        """Scelto > riconosciuto. Per una MFC Canon nota, un profilo riconosciuto senza i quattro
        contatori non deve bloccare: si legge dalla tabella standard."""
        from .snmp import COUNTER_MAP
        if self.profilo_scelto():
            return self.profilo_scelto()
        rilevato = (self.extra("test") or {}).get("profilo_id")
        profilo = ProfiloSNMP.objects.filter(pk=rilevato, attivo=True).first() if rilevato else None
        if (self.mfc() and profilo is not None and self._contatori_mancanti(profilo)
                and self._apparato().get("modello") in COUNTER_MAP):
            return None
        return profilo

    def profilo_diverso_dal_rilevato(self):
        """Nome del profilo riconosciuto dalla verifica se diverso da quello scelto (o None)."""
        scelto = self.profilo_scelto()
        rilevato = (self.extra("test") or {}).get("profilo_id")
        if scelto and rilevato and scelto.pk != rilevato:
            return (self.extra("test") or {}).get("profilo_nome", "")
        return None

    # --- blocchi ----------------------------------------------------------------
    def blocco(self, chiave):
        if chiave != "verifica":
            return ""
        if not self.test_valido():
            return "Esegui la verifica e fai in modo che riesca: senza verifica riuscita non si può completare."
        if not self.mfc():
            return ""
        # Una MFC senza i quattro contatori non si puo' riconciliare con la fattura.
        from .snmp import COUNTER_MAP
        profilo = self.profilo()
        if profilo is not None:
            mancanti = self._contatori_mancanti(profilo)
            if mancanti:
                return (f"Il profilo «{profilo}» non mappa i contatori {', '.join(mancanti)}: scegli un "
                        "profilo con i quattro contatori MFC o completalo dal catalogo profili.")
        elif self._apparato().get("modello") not in COUNTER_MAP:
            return ("Nessun profilo con i contatori per questo modello: scegli il modello qui sopra "
                    "(o indica al primo passo un modello Canon noto).")
        mappa = self.extra("mappatura")
        if not mappa or mappa.get("profilo_id") != (profilo.pk if profilo else None):
            return "Ripeti la verifica: per una MFC servono i quattro contatori letti con il modello scelto."
        errati = [r for r in mappa["righe"] if r["contatore"] and r["errore"]]
        if errati:
            return (f"[{errati[0]['errore']['codice']}] Contatore {errati[0]['contatore']} non leggibile: "
                    f"{errati[0]['errore']['azione']}")
        return ""

    def contesto_passo(self, chiave):
        ctx = {"mfc": self.mfc()}
        if chiave == "verifica":
            ctx.update(test=self.extra("test"), test_valido=self.test_valido(), profilo=self.profilo(),
                       mappatura=self.extra("mappatura"), profilo_diverso=self.profilo_diverso_dal_rilevato())
        elif chiave == "riepilogo" and not self._apparato().get("asset"):
            asset, motivo = self.proposta_asset()
            if asset is not None:
                ctx["proposta"] = {"asset": asset, "motivo": motivo}
        return ctx

    # --- azioni SNMP (fuori da transazioni) --------------------------------------
    def esegui_verifica(self):
        """Test di identita' e, se riesce, lettura dei valori del profilo (o contatori Canon)."""
        avviso = self.esegui_test()
        if avviso or not self.test_valido():
            return avviso
        return self.leggi_mappatura()

    def esegui_test(self):
        from .services import oid_riconoscimento_attivi, trova_profilo_snmp
        from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, _testo, leggi_oids
        parametri = self.parametri()
        if parametri is None:
            return "La connessione non è più valida: correggi il passo precedente."
        host, porta, versione, segreto = parametri
        esito = {"ok": False, "firma": self.firma(), "quando": timezone.now().isoformat()}
        errore = None
        # Come il polling notturno: anche gli OID di riconoscimento dei profili, per i
        # modelli con sysObjectID generico. Un OID assente non fa fallire la verifica.
        sonde = [oid for oid in oid_riconoscimento_attivi() if oid not in (SYS_DESCR, SYS_OBJECT_ID)]
        for tentativo in range(2):  # 1 retry, solo se il primo va in timeout
            try:
                valori, _errori = leggi_oids(host, [SYS_DESCR, SYS_OBJECT_ID, *sonde], community=segreto,
                                             port=porta, timeout=TEST_TIMEOUT, version=versione,
                                             max_duration=TEST_TIMEOUT + 2)
            except SNMPError as exc:
                errore = errori_snmp.da_eccezione(exc, host=host, porta=porta, timeout=TEST_TIMEOUT,
                                                  versione=versione if tentativo else None)
                if errore["codice"] != "SNMP-003":
                    break
                continue
            descr, object_id = _testo(valori.get(SYS_DESCR)), _testo(valori.get(SYS_OBJECT_ID))
            if not descr and not object_id:
                errore = errori_snmp.da_eccezione(errori_snmp.ErroreSNMPCatalogato(
                    "SNMP-005", "Il dispositivo risponde ma non espone sysDescr né sysObjectID."))
                break
            profilo = trova_profilo_snmp(sys_object_id=object_id, sys_description=descr,
                                         valori_riconoscimento={o: valori.get(o) for o in sonde if o in valori})
            esito.update(ok=True, sys_descr=descr[:500], sys_object_id=object_id[:255],
                         profilo_id=profilo.pk if profilo else None,
                         profilo_nome=str(profilo) if profilo else "")
            errore = None
            break
        if errore:
            esito["errore"] = errore
        self.imposta_extra("test", esito)
        self.imposta_extra("mappatura", None)  # valori letti con parametri vecchi: da rileggere
        return ""

    def audit_test(self):
        """Dettaglio audit della verifica: dove e con quale credenziale, mai il segreto."""
        esito, parametri = self.extra("test") or {}, self.parametri()
        conn = self.form_valido("connessione")
        salvata = conn.cleaned_data.get("community_salvata") if conn else None
        return {"host": parametri[0] if parametri else "", "porta": parametri[1] if parametri else None,
                "versione": parametri[2] if parametri else "",
                "credenziale": salvata.pk if salvata else ("nuova" if conn and conn._segreto_inline else "globale"),
                "esito": "ok" if esito.get("ok") else (esito.get("errore") or {}).get("codice", "")}

    def _righe_mappatura(self, colonne, valori, errori):
        righe = []
        for c in colonne:
            riga = {"nome": c.nome, "oid": c.oid, "contatore": c.contatore, "valore": None, "errore": None}
            if c.oid in valori:
                riga["valore"] = str(valori[c.oid])[:120]
                if c.contatore:
                    try:
                        errori_snmp.valore_numerico(valori[c.oid], c.nome)
                    except errori_snmp.ErroreSNMPCatalogato as exc:
                        riga["errore"] = errori_snmp.da_eccezione(exc)
            else:
                riga["errore"] = errori_snmp.da_eccezione(errori_snmp.ErroreSNMPCatalogato(
                    errori_snmp.classifica(errori.get(c.oid, "")).codice,
                    errori.get(c.oid, "nessuna risposta")[:300]))
            righe.append(riga)
        return righe

    def leggi_mappatura(self):
        """Profilo: colonne del profilo. MFC Canon nota senza profilo: tabella contatori standard."""
        from .snmp import COUNTER_MAP, SNMPError, leggi_macchina, leggi_specifiche
        profilo, parametri = self.profilo(), self.parametri()
        if parametri is None or not self.test_valido():
            return "Serve una verifica riuscita per leggere i valori."
        host, porta, versione, segreto = parametri
        if profilo is None:
            modello = self._apparato().get("modello")
            if not self.mfc() or modello not in COUNTER_MAP:
                return ""
            colonne = [SimpleNamespace(nome=f"Contatore {numero}", oid=f"Canon {numero}", contatore=campo)
                       for campo, numero in COUNTER_MAP[modello].items()]
            try:
                letti = leggi_macchina(SimpleNamespace(host=host, modello=modello), community=segreto,
                                       port=porta, timeout=TEST_TIMEOUT, version=versione)
                valori, errori = {c.oid: letti[c.contatore] for c in colonne}, {}
            except SNMPError as exc:
                valori, errori = {}, {c.oid: str(exc) for c in colonne}
            self.imposta_extra("mappatura", {"profilo_id": None, "canon": True,
                                             "righe": self._righe_mappatura(colonne, valori, errori)})
            return ""
        colonne = [SimpleNamespace(nome=c.nome, oid=c.oid, modalita=c.modalita, aggregazione=c.aggregazione,
                                   contatore=c.get_contatore_mfc_display() if c.contatore_mfc else "")
                   for c in profilo.colonne.filter(attiva=True).order_by("ordine", "pk")[:MAX_COLONNE_MAPPATURA]]
        specifiche = [{"oid": c.oid, "modalita": c.modalita, "aggregazione": c.aggregazione} for c in colonne]
        try:
            valori, errori = leggi_specifiche(host, specifiche, community=segreto, port=porta,
                                              timeout=TEST_TIMEOUT, version=versione)
        except SNMPError as exc:
            valori, errori = {}, {c.oid: str(exc) for c in colonne}
        self.imposta_extra("mappatura", {"profilo_id": profilo.pk,
                                         "righe": self._righe_mappatura(colonne, valori, errori)})
        return ""

    def proposta_asset(self):
        """(asset, motivo) trovato per matricola o IP quando al primo passo non se ne e' scelto uno."""
        from .services import trova_asset_snmp
        parametri = self.parametri()
        if parametri is None:
            return None, ""
        try:
            return trova_asset_snmp(seriale=self._apparato().get("matricola", ""), host=parametri[0])
        except Exception:  # la proposta e' facoltativa: non deve bloccare il passo
            logger.exception("Proposta asset non disponibile nel wizard per %s", parametri[0])
            return None, ""

    def collega_proposta(self):
        asset, _motivo = self.proposta_asset()
        if asset is None:
            return "Nessun asset da collegare."
        self.stato["dati"].setdefault("apparato", {})["asset"] = str(asset.pk)
        self._salva()
        return ""

    def _credenziale(self, host, conn):
        """CommunitySNMP da usare: quella scelta, oppure una nuova cifrata nel catalogo."""
        from .credential_crypto import cifra
        if conn._segreto_inline:
            versione = conn.cleaned_data["versione"]
            prefisso = "stampante" if self.mfc() else "dispositivo"
            base = f"{'SNMPv3' if versione == 'v3' else 'Community'} {prefisso} {host}"[:72]
            nome, n = base, 1
            # Mai sovrascrivere una voce esistente del catalogo: altri apparati potrebbero usarla.
            while CommunitySNMP.objects.filter(nome=nome).exists():
                n += 1
                nome = f"{base} ({n})"
            return CommunitySNMP.objects.create(nome=nome, versione=versione,
                                                segreto_cifrato=cifra(conn._segreto_inline))
        return conn.cleaned_data.get("community_salvata")

    # --- riepilogo e salvataggio -------------------------------------------------
    def riepilogo(self):
        dati = self._apparato()
        tipi = dict(PassoApparatoForm.base_fields["tipo_apparato"].choices)
        righe = [("Tipo", tipi.get(dati.get("tipo_apparato"), "—")),
                 ("Reparto" if self.mfc() else "Nome", dati.get("nome") or "—"),
                 ("Matricola", dati.get("matricola") or "—"), ("Modello", dati.get("modello") or "—")]
        if self.mfc():
            righe.append(("Contratto", dati.get("contratto") or "—"))
        else:
            righe.append(("Reparto / posizione", dati.get("posizione") or "—"))
        asset = dati.get("asset")
        righe.append(("Asset", f"{asset.asset_tag} · {asset.name}" if asset else "Non collegato"))
        conn = self.form_valido("connessione")
        if conn:
            righe += [("Indirizzo", f"{conn.cleaned_data['host']}:{conn.cleaned_data['porta']}"),
                      ("Versione", conn.cleaned_data["versione"])]
            if conn._segreto_inline:
                origine = "Nuova credenziale, salvata cifrata nel catalogo"
            elif conn.cleaned_data.get("community_salvata"):
                origine = f"Catalogo: {conn.cleaned_data['community_salvata'].nome}"
            else:
                origine = "Community della configurazione globale"
            righe.append(("Credenziali", origine))
        profilo = self.profilo()
        righe.append(("Modello SNMP", str(profilo) if profilo else
                      ("Tabella Canon standard" if self.mfc() else "Nessuno: identità e uptime")))
        righe.append(("Verifica", "riuscita" if self.test_valido() else "da ripetere"))
        return righe

    def salva(self, *, bozza):
        """Crea la MFC o il dispositivo. Senza bozza servono tutti i passi validi e la verifica."""
        app, conn = self.form_valido("apparato"), self.form_valido("connessione")
        if app is None or conn is None or (not bozza and (not self.test_valido() or self.blocco("verifica"))):
            raise ValueError("wizard incompleto")
        if bozza and self.mfc():
            raise ValueError("bozza non ammessa per le MFC")
        dati, host = app.cleaned_data, conn.cleaned_data["host"]
        with transaction.atomic():
            if self.mfc():
                obj = Macchina(
                    reparto=dati["nome"], matricola=dati["matricola"], modello=dati.get("modello", ""),
                    contratto=dati.get("contratto", ""), fornitore=dati["fornitore"],
                    host=host, snmp_porta=conn.cleaned_data["porta"], snmp_versione=conn.cleaned_data["versione"],
                    community_salvata=self._credenziale(host, conn), profilo_snmp=self.profilo(),
                    asset=dati.get("asset"), attiva=True,
                    snmp_stato=StatoSNMP.OK, snmp_ultimo_controllo=timezone.now(),
                )
                obj.full_clean()
                obj.save()
            else:
                esito, verificato = self.extra("test") or {}, self.test_valido()
                obj = DispositivoSNMP(
                    nome=dati["nome"], categoria=dati["tipo_apparato"], host=host,
                    porta=conn.cleaned_data["porta"], versione=conn.cleaned_data["versione"],
                    community_salvata=self._credenziale(host, conn), profilo_snmp=self.profilo(),
                    verificato=verificato, posizione=dati.get("posizione", ""), note=dati.get("note", ""),
                    matricola=dati.get("matricola", ""), modello=dati.get("modello", ""),
                    produttore=valori_asset(dati.get("asset")).get("produttore", "")[:120],
                    asset=dati.get("asset"),
                )
                if verificato:
                    obj.snmp_stato = StatoSNMP.OK
                    obj.snmp_ultimo_controllo = timezone.now()
                    obj.sys_description = esito.get("sys_descr", "")
                    obj.sys_object_id = esito.get("sys_object_id", "")
                obj.save()
                if obj.profilo_snmp_id:
                    from .services import applica_profilo_dispositivo
                    applica_profilo_dispositivo(obj, obj.profilo_snmp)
        self.chiudi()
        return obj

    def fine(self, obj, *, bozza):
        if isinstance(obj, Macchina):
            return (reverse("contatori:macchina", args=[obj.pk]), "success",
                    f"Stampante «{obj.reparto}» creata e verificata.", "macchina_creata_wizard",
                    {"matricola": obj.matricola, "host": obj.host})
        url = reverse("contatori:snmp_dispositivo", args=[obj.pk])
        if not bozza:
            return (url, "success", f"Dispositivo «{obj.nome}» creato e verificato.",
                    "snmp_dispositivo_creato_wizard", {"host": obj.host, "profilo": str(obj.profilo_snmp or "")})
        if obj.verificato:
            testo, livello = f"«{obj.nome}» salvato: la verifica era già riuscita.", "success"
        else:
            testo, livello = (f"«{obj.nome}» salvato come bozza NON verificata: "
                              "verrà verificato alla prima lettura SNMP riuscita."), "warning"
        return url, livello, testo, "snmp_dispositivo_bozza", {"host": obj.host, "verificato": obj.verificato}


def _registro():
    from .wizard_modelli import WizardColonna, WizardProfilo, WizardSonda
    return {w.tipo: w for w in (WizardApparato, WizardProfilo, WizardColonna, WizardSonda)}


def wizard_per_tipo(tipo):
    """Classe del wizard per ``tipo`` (KeyError se non esiste); gli slug storici aprono «apparato»."""
    if tipo in ALIAS_APPARATO:
        return WizardApparato
    return _registro()[tipo]
