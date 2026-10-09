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
    CAMPI_SEGRETI, PassoAnagraficaMacchinaForm, PassoAssociazioneForm,
    PassoAssociazioneMacchinaForm, PassoCredenzialiForm, PassoReteForm, PassoTipoForm,
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


# --- Connessione SNMP: rete, credenziali, test, mappatura -------------------------

class ConnessioneSNMPMixin:
    """Passi «rete», «credenziali», «test», «mappatura» condivisi da dispositivo e MFC.

    ``chiave_tipo``: passo con il campo ``profilo`` scelto dall'utente.
    """
    chiave_tipo = "tipo"
    prefisso_credenziale = "dispositivo"
    azioni = {"test": ("test", "esegui_test"), "leggi": ("mappatura", "leggi_mappatura")}

    def memorizza(self, chiave, form):
        super().memorizza(chiave, form)
        if chiave == "rete":
            # Si salva l'IP gia' risolto: niente DNS a ogni rivalidazione e firma del test stabile
            # anche con DNS round-robin. Il nome digitato resta solo per la visualizzazione.
            self.stato["dati"]["rete"].update(host=form.cleaned_data["host"], nome_digitato=form.data.get("host", ""))
            self._salva()

    def kwargs_form(self, chiave):
        if chiave == "credenziali":
            return {"globale_disponibile": bool(ImpostazioniSNMP.get_solo().community)}
        return {}

    def form(self, chiave, data=None):
        form = super().form(chiave, data)
        if chiave == "credenziali" and form is not None:
            # La versione arriva dal passo «Rete»: unica fonte, il campo nascosto la ricalca.
            versione = (self.dati("rete").get("versione") or "v2c")
            if form.is_bound:
                form.data = form.data.copy() if hasattr(form.data, "copy") else dict(form.data)
                form.data["versione"] = versione
            else:
                form.initial["versione"] = versione
        return form

    def blocco(self, chiave):
        if chiave == "test" and not self.test_valido():
            return ("Esegui il test di connessione e fai in modo che riesca: "
                    "senza test superato non si può completare.")
        return ""

    def contesto_passo(self, chiave):
        ctx = {"test": self.extra("test"), "test_valido": self.test_valido(), "profilo": self.profilo(),
               "mappatura": self.extra("mappatura")}
        if chiave == "test":
            ctx["profilo_diverso"] = self.profilo_diverso_dal_rilevato()
        return ctx

    # --- parametri risolti ---------------------------------------------------
    def parametri(self):
        """(host, porta, versione, segreto) dai passi validi; segreto mai salvato in chiaro."""
        from .credential_crypto import decifra
        rete, cred = self.form_valido("rete"), self.form_valido("credenziali")
        if rete is None or cred is None:
            return None
        versione = rete.cleaned_data["versione"]
        salvata = cred.cleaned_data.get("community_salvata")
        if cred._segreto_inline:
            segreto = cred._segreto_inline
        elif salvata is not None:
            segreto = decifra(salvata.segreto_cifrato)
        else:
            segreto = ImpostazioniSNMP.get_solo().community
        return rete.cleaned_data["host"], rete.cleaned_data["porta"], versione, segreto

    def firma(self):
        """Impronta di rete+credenziali: se cambiano dopo il test, il test va rifatto."""
        parametri = self.parametri()
        if parametri is None:
            return ""
        return salted_hmac("contatori.wizard.test", "|".join(map(str, parametri))).hexdigest()

    def test_valido(self):
        esito = self.extra("test") or {}
        return bool(esito.get("ok")) and esito.get("firma") == self.firma() != ""

    def profilo_scelto(self):
        tipo = self.form_valido(self.chiave_tipo)
        return tipo.cleaned_data.get("profilo") if tipo is not None else None

    def profilo(self):
        if self.profilo_scelto():
            return self.profilo_scelto()
        rilevato = (self.extra("test") or {}).get("profilo_id")
        return ProfiloSNMP.objects.filter(pk=rilevato, attivo=True).first() if rilevato else None

    def profilo_diverso_dal_rilevato(self):
        """Nome del profilo riconosciuto dal test se diverso da quello scelto (o None)."""
        scelto = self.profilo_scelto()
        rilevato = (self.extra("test") or {}).get("profilo_id")
        if scelto and rilevato and scelto.pk != rilevato:
            return (self.extra("test") or {}).get("profilo_nome", "")
        return None

    # --- azioni SNMP (fuori da transazioni) ------------------------------------
    def esegui_test(self):
        """Ritorna un avviso per l'utente ("" se il test e' stato eseguito)."""
        from .services import oid_riconoscimento_attivi, trova_profilo_snmp
        from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, _testo, leggi_oids
        parametri = self.parametri()
        if parametri is None:
            return "Rete o credenziali non sono più valide: correggi i passi precedenti."
        host, porta, versione, segreto = parametri
        esito = {"ok": False, "firma": self.firma(), "quando": timezone.now().isoformat()}
        errore = None
        # Come il polling notturno: anche gli OID di riconoscimento dei profili, per i
        # modelli con sysObjectID generico. Un OID assente non fa fallire il test.
        sonde = [oid for oid in oid_riconoscimento_attivi() if oid not in (SYS_DESCR, SYS_OBJECT_ID)]
        for _tentativo in range(2):  # 1 retry, solo se il primo va in timeout
            try:
                valori, _errori = leggi_oids(host, [SYS_DESCR, SYS_OBJECT_ID, *sonde], community=segreto,
                                             port=porta, timeout=TEST_TIMEOUT, version=versione,
                                             max_duration=TEST_TIMEOUT + 2)
            except SNMPError as exc:
                errore = errori_snmp.da_eccezione(exc, host=host, porta=porta, timeout=TEST_TIMEOUT)
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
        """Dettaglio audit del test: dove e con quale credenziale, mai il segreto."""
        esito, parametri = self.extra("test") or {}, self.parametri()
        cred = self.form_valido("credenziali")
        salvata = cred.cleaned_data.get("community_salvata") if cred else None
        return {"host": parametri[0] if parametri else "", "porta": parametri[1] if parametri else None,
                "versione": parametri[2] if parametri else "",
                "credenziale": salvata.pk if salvata else ("nuova" if cred and cred._segreto_inline else "globale"),
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
        from .snmp import SNMPError, leggi_specifiche
        profilo, parametri = self.profilo(), self.parametri()
        if profilo is None or parametri is None or not self.test_valido():
            return "Serve un test riuscito e un profilo per leggere i valori."
        host, porta, versione, segreto = parametri
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

    def proposta_asset(self, seriale=""):
        from .services import trova_asset_snmp
        parametri = self.parametri()
        if parametri is None:
            return None, ""
        try:
            return trova_asset_snmp(seriale=seriale, host=parametri[0])
        except Exception:  # la proposta e' facoltativa: non deve bloccare il passo
            logger.exception("Proposta asset non disponibile nel wizard per %s", parametri[0])
            return None, ""

    def _credenziale(self, host, cred):
        """CommunitySNMP da usare: quella scelta, oppure una nuova cifrata nel catalogo."""
        from .credential_crypto import cifra
        if cred._segreto_inline:
            versione = cred.cleaned_data["versione"]
            base = f"{'SNMPv3' if versione == 'v3' else 'Community'} {self.prefisso_credenziale} {host}"[:72]
            nome, n = base, 1
            # Mai sovrascrivere una voce esistente del catalogo: altri apparati potrebbero usarla.
            while CommunitySNMP.objects.filter(nome=nome).exists():
                n += 1
                nome = f"{base} ({n})"
            return CommunitySNMP.objects.create(nome=nome, versione=versione,
                                                segreto_cifrato=cifra(cred._segreto_inline))
        return cred.cleaned_data.get("community_salvata")

    def _riepilogo_connessione(self):
        rete, cred = self.form_valido("rete"), self.form_valido("credenziali")
        righe = []
        if rete:
            righe += [("Indirizzo", f"{rete.cleaned_data['host']}:{rete.cleaned_data['porta']}"),
                      ("Versione", rete.cleaned_data["versione"])]
        if cred:
            if cred._segreto_inline:
                origine = "Nuova credenziale, salvata cifrata nel catalogo"
            elif cred.cleaned_data.get("community_salvata"):
                origine = f"Catalogo: {cred.cleaned_data['community_salvata'].nome}"
            else:
                origine = "Community della configurazione globale"
            righe.append(("Credenziali", origine))
        profilo = self.profilo()
        righe.append(("Profilo", str(profilo) if profilo else "Nessuno"))
        righe.append(("Test di connessione", "superato" if self.test_valido() else "da ripetere"))
        return righe


_PASSI_CONNESSIONE = (
    Passo("rete", "Rete", "Dove si trova in rete e quale versione SNMP usa.", PassoReteForm),
    Passo("credenziali", "Credenziali", "Con cosa il portale si presenta all'apparato.", PassoCredenzialiForm),
    Passo("test", "Test di connessione", "Obbligatorio: il portale legge identità e modello."),
    Passo("mappatura", "Mappatura contatori", "Valori realmente letti per ogni colonna del profilo."),
)


# --- Wizard «Nuovo dispositivo SNMP» ---------------------------------------------

class WizardDispositivo(ConnessioneSNMPMixin, MotoreWizard):
    tipo = "dispositivo"
    titolo = "Nuovo dispositivo SNMP"
    consente_bozza = True
    passi = (
        Passo("tipo", "Tipo e modello", "Che apparato è e, se lo conosci, il suo modello.", PassoTipoForm),
        *_PASSI_CONNESSIONE,
        Passo("associazione", "Asset e reparto", "Collega il dispositivo al registro Asset.",
              PassoAssociazioneForm),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )

    @classmethod
    def da_query(cls, get):
        """Precompilazione dai link di Discovery: solo valori grezzi, validati dai form dei passi."""
        dati = {}
        if get.get("nome"):
            dati["tipo"] = {"nome": get["nome"][:100]}
        rete = {k: get[k][:253] for k in ("host", "porta", "versione") if get.get(k)}
        if rete:
            dati["rete"] = {"porta": "161", "versione": "v2c", **rete}
        if (get.get("community_id") or "").isdigit():
            dati["credenziali"] = {"community_salvata": get["community_id"]}
        return dati, {}

    def riepilogo(self):
        tipo, assoc = self.form_valido("tipo"), self.form_valido("associazione")
        righe = []
        if tipo:
            categorie = dict(tipo.fields["categoria"].choices)
            righe += [("Nome", tipo.cleaned_data["nome"]), ("Tipo", categorie.get(tipo.cleaned_data["categoria"]))]
        righe += self._riepilogo_connessione()
        if assoc:
            asset = assoc.cleaned_data.get("asset")
            righe += [("Asset", f"{asset.asset_tag} · {asset.name}" if asset else "Non collegato"),
                      ("Reparto / posizione", assoc.cleaned_data.get("posizione") or "—")]
        return righe

    def salva(self, *, bozza):
        """Crea il dispositivo. Senza bozza servono tutti i passi validi e il test superato."""
        tipo, rete = self.form_valido("tipo"), self.form_valido("rete")
        cred = self.form_valido("credenziali")
        assoc = self.form_valido("associazione")
        if tipo is None or rete is None or (not bozza and (cred is None or not self.test_valido())):
            raise ValueError("wizard incompleto")
        esito = self.extra("test") or {}
        verificato = self.test_valido()
        host = rete.cleaned_data["host"]
        with transaction.atomic():
            dispositivo = DispositivoSNMP(
                nome=tipo.cleaned_data["nome"], categoria=tipo.cleaned_data["categoria"], host=host,
                porta=rete.cleaned_data["porta"], versione=rete.cleaned_data["versione"],
                community_salvata=self._credenziale(host, cred) if cred is not None else None,
                profilo_snmp=self.profilo(), verificato=verificato,
                posizione=assoc.cleaned_data["posizione"] if assoc else "",
                note=assoc.cleaned_data["note"] if assoc else "",
                asset=assoc.cleaned_data["asset"] if assoc else None,
            )
            if verificato:
                dispositivo.snmp_stato = StatoSNMP.OK
                dispositivo.snmp_ultimo_controllo = timezone.now()
                dispositivo.sys_description = esito.get("sys_descr", "")
                dispositivo.sys_object_id = esito.get("sys_object_id", "")
            dispositivo.save()
            if dispositivo.profilo_snmp_id:
                from .services import applica_profilo_dispositivo
                applica_profilo_dispositivo(dispositivo, dispositivo.profilo_snmp)
        self.chiudi()
        return dispositivo

    def fine(self, obj, *, bozza):
        url = reverse("contatori:snmp_dispositivo", args=[obj.pk])
        if not bozza:
            return (url, "success", f"Dispositivo «{obj.nome}» creato e verificato.",
                    "snmp_dispositivo_creato_wizard", {"host": obj.host, "profilo": str(obj.profilo_snmp or "")})
        if obj.verificato:
            testo, livello = f"«{obj.nome}» salvato: il test di connessione era già riuscito.", "success"
        else:
            testo, livello = (f"«{obj.nome}» salvato come bozza NON verificata: "
                              "verrà verificato alla prima lettura SNMP riuscita."), "warning"
        return url, livello, testo, "snmp_dispositivo_bozza", {"host": obj.host, "verificato": obj.verificato}

    def contesto_passo(self, chiave):
        ctx = super().contesto_passo(chiave)
        if chiave == "associazione":
            ctx["proposta_asset"] = self.proposta_asset
        return ctx


# --- Wizard «Nuova stampante MFC» ------------------------------------------------

CAMPI_MFC = ("a4_bn", "a3_bn", "a4_col", "a3_col")


class WizardMacchina(ConnessioneSNMPMixin, MotoreWizard):
    """MFC letta via SNMP. Una MFC senza IP (solo letture manuali) usa il modulo completo."""
    tipo = "macchina"
    titolo = "Nuova stampante MFC"
    chiave_tipo = "anagrafica"
    prefisso_credenziale = "stampante"
    passi = (
        Passo("anagrafica", "Anagrafica e contratto", "Reparto, matricola, modello e contratto di fornitura.",
              PassoAnagraficaMacchinaForm),
        *_PASSI_CONNESSIONE,
        Passo("associazione", "Asset", "Collega la stampante al registro Asset.", PassoAssociazioneMacchinaForm),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )

    def url_annulla(self):
        return reverse("contatori:macchine")

    def _anagrafica(self):
        form = self.form_valido("anagrafica")
        return form.cleaned_data if form is not None else {}

    @staticmethod
    def _contatori_mancanti(profilo):
        presenti = set(profilo.colonne.filter(attiva=True).exclude(contatore_mfc="")
                       .values_list("contatore_mfc", flat=True))
        return [c for c in CAMPI_MFC if c not in presenti]

    def profilo(self):
        """Il profilo scelto vince; uno riconosciuto ma senza i quattro contatori non deve
        bloccare un Canon iR-ADV noto, che si legge dalla tabella standard."""
        from .snmp import COUNTER_MAP
        if self.profilo_scelto():
            return self.profilo_scelto()
        rilevato = super().profilo()
        if (rilevato is not None and self._contatori_mancanti(rilevato)
                and self._anagrafica().get("modello") in COUNTER_MAP):
            return None
        return rilevato

    def blocco(self, chiave):
        messaggio = super().blocco(chiave)
        if messaggio or chiave != "mappatura":
            return messaggio
        # Una MFC senza i quattro contatori non si puo' riconciliare con la fattura.
        from .snmp import COUNTER_MAP
        profilo = self.profilo()
        if profilo is not None:
            mancanti = self._contatori_mancanti(profilo)
            if mancanti:
                return (f"Il profilo «{profilo}» non mappa i contatori {', '.join(mancanti)}: scegli un "
                        "profilo con i quattro contatori MFC o completalo dal catalogo profili.")
        elif self._anagrafica().get("modello") not in COUNTER_MAP:
            return ("Nessun profilo con i contatori per questo modello: sceglilo al primo passo "
                    "(o un modello Canon noto).")
        # I quattro contatori devono essere stati letti davvero, con valori numerici.
        mappa = self.extra("mappatura")
        if not mappa or mappa.get("profilo_id") != (profilo.pk if profilo else None):
            return "Leggi i contatori: per una MFC servono i quattro valori reali prima di proseguire."
        errati = [r for r in mappa["righe"] if r["contatore"] and r["errore"]]
        if errati:
            return (f"[{errati[0]['errore']['codice']}] Contatore {errati[0]['contatore']} non leggibile: "
                    f"{errati[0]['errore']['azione']}")
        return ""

    def leggi_mappatura(self):
        """Profilo: colonne del profilo. Canon noto senza profilo: tabella contatori standard."""
        from .snmp import COUNTER_MAP, SNMPError, leggi_macchina
        if self.profilo() is not None:
            return super().leggi_mappatura()
        modello, parametri = self._anagrafica().get("modello"), self.parametri()
        if modello not in COUNTER_MAP or parametri is None or not self.test_valido():
            return "Serve un test riuscito e un profilo (o un modello Canon noto) per leggere i contatori."
        host, porta, versione, segreto = parametri
        colonne = [SimpleNamespace(nome=f"Contatore {numero}", oid=f"Canon {numero}", contatore=campo)
                   for campo, numero in COUNTER_MAP[modello].items()]
        try:
            letti = leggi_macchina(SimpleNamespace(host=host, modello=modello), community=segreto,
                                   port=porta, timeout=TEST_TIMEOUT, version=versione)
            valori, errori = {c.oid: letti[c.contatore] for c in colonne}, {}
        except SNMPError as exc:
            valori, errori = {}, {c.oid: str(exc) for c in colonne}
        self.imposta_extra("mappatura", {"profilo_id": None,
                                         "righe": self._righe_mappatura(colonne, valori, errori)})
        return ""

    def contesto_passo(self, chiave):
        ctx = super().contesto_passo(chiave)
        if chiave == "associazione":
            ctx["proposta_asset"] = lambda: self.proposta_asset(seriale=self._anagrafica().get("matricola", ""))
        return ctx

    def riepilogo(self):
        dati = self._anagrafica()
        righe = [("Reparto", dati.get("reparto", "")), ("Matricola", dati.get("matricola", "")),
                 ("Modello", dati.get("modello") or "—"), ("Contratto", dati.get("contratto") or "—")]
        righe += self._riepilogo_connessione()
        assoc = self.form_valido("associazione")
        if assoc:
            asset = assoc.cleaned_data.get("asset")
            righe.append(("Asset", f"{asset.asset_tag} · {asset.name}" if asset else "Non collegato"))
        return righe

    def salva(self, *, bozza):
        anag, rete = self.form_valido("anagrafica"), self.form_valido("rete")
        cred, assoc = self.form_valido("credenziali"), self.form_valido("associazione")
        if None in (anag, rete, cred) or not self.test_valido() or self.blocco("mappatura"):
            raise ValueError("wizard incompleto")
        host = rete.cleaned_data["host"]
        with transaction.atomic():
            macchina = Macchina(
                **{k: anag.cleaned_data[k] for k in ("reparto", "matricola", "modello", "contratto", "fornitore")},
                host=host, snmp_porta=rete.cleaned_data["porta"], snmp_versione=rete.cleaned_data["versione"],
                community_salvata=self._credenziale(host, cred), profilo_snmp=self.profilo(),
                asset=assoc.cleaned_data.get("asset") if assoc else None,
                attiva=assoc.cleaned_data.get("attiva", True) if assoc else True,
                snmp_stato=StatoSNMP.OK, snmp_ultimo_controllo=timezone.now(),
            )
            macchina.full_clean()
            macchina.save()
        self.chiudi()
        return macchina

    def fine(self, obj, *, bozza):
        return (reverse("contatori:macchina", args=[obj.pk]), "success",
                f"Stampante «{obj.reparto}» creata e verificata.", "macchina_creata_wizard",
                {"matricola": obj.matricola, "host": obj.host})


def _registro():
    from .wizard_modelli import WizardColonna, WizardProfilo, WizardSonda
    return {w.tipo: w for w in (WizardDispositivo, WizardMacchina, WizardProfilo, WizardColonna, WizardSonda)}


def wizard_per_tipo(tipo):
    """Classe del wizard per ``tipo`` (KeyError se non esiste)."""
    return _registro()[tipo]
