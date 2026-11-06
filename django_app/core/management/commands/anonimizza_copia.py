"""Anonimizza la copia locale del database di produzione. Non stampa mai i valori.

    manage.py anonimizza_copia --settings=config.settings.copia_anonima --esegui
    manage.py anonimizza_copia --settings=config.settings.copia_anonima --elenco   # solo classificazione

Procedura: ``docs/dr/COPIA_PROD_ANONIMIZZATA.md``. Rifiuta qualunque database che non sia ``*_ANON``
su questa macchina.
"""
from __future__ import annotations

import re
import secrets

from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.copia_anonima import regole as R

NOMI_FINTI = "Marco Giulia Luca Sara Paolo Elena Andrea Chiara Davide Laura Matteo Anna Stefano Marta Simone Silvia Fabio Irene Enrico Valeria".split()
COGNOMI_FINTI = "Prova Collaudo Esempio Fittizio Campione Modello Demo Saggio Verifica Bozza Simulato Finto Tester Pilota Facsimile Mock Dummy Sample".split()
RX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RX_CF = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE)
RX_IBAN = re.compile(r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b", re.IGNORECASE)


def q(nome: str) -> str:
    return "[" + nome.replace("]", "]]") + "]"


def _scelta(valori: list[str], hash_sql: str, da: int = 1) -> str:
    lista = ",".join("N'" + v + "'" for v in valori)
    return f"CHOOSE(1 + CONVERT(int, SUBSTRING({hash_sql}, {da}, 2)) % {len(valori)}, {lista})"


def espressione(azione: str, col: str, lunghezza: int | None, sale: str) -> str:
    """Espressione SQL del nuovo valore. Il sale casuale non viene salvato: non si torna indietro."""
    testo = f"CAST({col} AS nvarchar(max))"
    hash_b = f"HASHBYTES('SHA2_256', N'{sale}' + {testo})"
    hex_ = f"CONVERT(varchar(64), {hash_b}, 2)"
    massimo = lunghezza if lunghezza and lunghezza > 0 else 4000

    def taglia(prefisso: str, corpo: str) -> str:
        if massimo < len(prefisso) + 6:
            return f"LEFT({hex_}, {massimo})"
        return f"LEFT(N'{prefisso}' + {corpo}, {massimo})"

    if azione == R.EMAIL:
        if massimo < 30:
            return f"LEFT({hex_}, {massimo})"
        hash_mail = f"CONVERT(varchar(64), HASHBYTES('SHA2_256', N'{sale}' + LOWER({testo})), 2)"
        return f"LEFT(N'u' + LOWER(LEFT({hash_mail}, 12)) + N'@example.invalid', {massimo})"
    if azione == R.UTENTE:
        hash_utente = f"CONVERT(varchar(64), HASHBYTES('SHA2_256', N'{sale}' + LOWER({testo})), 2)"
        return f"LEFT(N'u' + LOWER(LEFT({hash_utente}, 12)), {massimo})"
    if azione == R.SEGRETO:
        return taglia("x", hex_)
    if azione == R.NOME:
        return f"LEFT({_scelta(NOMI_FINTI, hash_b)}, {massimo})"
    if azione == R.COGNOME:
        return f"LEFT({_scelta(COGNOMI_FINTI, hash_b)}, {massimo})"
    if azione == R.PERSONA:
        if massimo < 8:
            return f"LEFT({hex_}, {massimo})"
        return (f"LEFT({_scelta(COGNOMI_FINTI, hash_b)} + N' ' + {_scelta(NOMI_FINTI, hash_b, 3)}"
                f" + N' ' + LEFT({hex_}, 4), {massimo})")
    if azione == R.UUID:
        return f"LOWER(LEFT({hex_}, 32))"
    if azione == R.CONTATTO:
        return f"LEFT({hex_}, {massimo})"
    # Testo libero: i JSON restano JSON vuoti, numeri e date brevi restano, il resto si sostituisce.
    return (
        f"CASE WHEN LEFT(LTRIM({testo}), 1) = N'{{' AND ISJSON({testo}) = 1 THEN N'{{}}' "
        f"WHEN LEFT(LTRIM({testo}), 1) = N'[' AND ISJSON({testo}) = 1 THEN N'[]' "
        f"WHEN LEN({testo}) <= 12 AND {testo} NOT LIKE N'%[^0-9 .,:/-]%' THEN {testo} "
        f"ELSE {taglia('Testo ', hex_)} END"
    )


class Command(BaseCommand):
    help = "Anonimizza la copia locale *_ANON del database di produzione."

    def add_arguments(self, parser):
        parser.add_argument("--esegui", action="store_true", help="Scrive sulla copia.")
        parser.add_argument("--elenco", action="store_true", help="Stampa solo la classificazione delle colonne.")
        parser.add_argument("--password-collaudo", default="", help="Password dell'utente di prova (se vuota viene generata).")

    def handle(self, *args, **opts):
        if not opts["esegui"] and not opts["elenco"]:
            raise CommandError("Indicare --esegui o --elenco.")
        self._verifica_bersaglio()
        colonne = self._inventario()
        scelte, tipi_campo = self._metadati_campi()
        azioni = {
            (tabella, colonna): (
                R.adatta_al_campo(
                    R.classifica(tabella, colonna, tipo, (tabella, colonna) in scelte),
                    tipi_campo.get((tabella, colonna)),
                ),
                lung,
            )
            for tabella, colonna, tipo, lung in colonne
        }
        if opts["elenco"]:
            for (tabella, colonna), (azione, _) in sorted(azioni.items()):
                self.stdout.write(f"{tabella}|{colonna}|{R.classifica_tabella(tabella) or azione}")
            return

        self._esegui_sql("ALTER DATABASE CURRENT SET RECOVERY SIMPLE")
        indice = self._raccogli_identificativi(colonne)
        tabelle = sorted(self._tutte_le_tabelle())
        self._blocca_vincoli(tabelle)
        errori: list[str] = []
        svuotate = self._svuota([t for t in tabelle if R.classifica_tabella(t)], errori)
        sale = secrets.token_hex(16)
        fatte = 0
        for (tabella, colonna), (azione, lung) in sorted(azioni.items()):
            if tabella not in svuotate and self._applica(tabella, colonna, azione, lung, sale, errori):
                fatte += 1
        self._non_testo(errori)
        self._valori_nei_tenuti(azioni, svuotate, sale, errori)
        corrette = self._correggi_residui(azioni, svuotate, indice, sale, errori)
        self._accessi(opts["password_collaudo"], errori)
        self._sblocca_vincoli(tabelle)
        self.stdout.write(
            f"Tabelle svuotate: {len(svuotate)}. Colonne sostituite: {fatte}. Colonne corrette dal controllo finale: {corrette}."
        )
        residui, dubbi = self._conta_residui(azioni, svuotate, indice)
        for voce in dubbi:
            self.stdout.write(f"DA GUARDARE (solo cognome): {voce}")
        for voce in errori:
            self.stdout.write(self.style.ERROR(f"ERRORE: {voce}"))
        for voce in residui:
            self.stdout.write(self.style.ERROR(f"RESIDUO: {voce}"))
        if errori or residui:
            raise CommandError(f"Anonimizzazione NON riuscita: {len(errori)} errori, {len(residui)} colonne con residui.")
        self.stdout.write(self.style.SUCCESS("Anonimizzazione riuscita: nessun identificativo noto residuo."))

    # --- guardie ---------------------------------------------------------------------------------
    def _verifica_bersaglio(self):
        if not getattr(settings, "COPIA_ANONIMA", False):
            raise CommandError("Si esegue solo con --settings=config.settings.copia_anonima.")
        conf = connection.settings_dict
        if conf.get("ENGINE") != "mssql":
            raise CommandError("Si esegue solo su SQL Server.")
        nome = str(conf.get("NAME") or "")
        if not nome.upper().endswith("_ANON"):
            raise CommandError(f"Database rifiutato: {nome!r} non finisce con _ANON.")
        attuale, macchina, client = self._righe(
            "SELECT DB_NAME(), CAST(SERVERPROPERTY('MachineName') AS nvarchar(128)), HOST_NAME()"
        )[0]
        if attuale != nome or str(macchina).lower() != str(client).lower():
            raise CommandError("Database rifiutato: non e' la copia su questa macchina.")

    # --- letture ---------------------------------------------------------------------------------
    def _esegui_sql(self, sql, params=None):
        with connection.cursor() as cur:
            cur.execute(sql, params)

    def _righe(self, sql, params=None):
        with connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _tutte_le_tabelle(self):
        return {r[0] for r in self._righe("SELECT name FROM sys.tables WHERE is_ms_shipped = 0")}

    def _inventario(self):
        return [tuple(r) for r in self._righe(
            """SELECT t.name, c.name, ty.name,
                      CASE WHEN c.max_length = -1 THEN NULL
                           WHEN ty.name IN ('nvarchar','nchar') THEN c.max_length / 2 ELSE c.max_length END
               FROM sys.columns c JOIN sys.tables t ON t.object_id = c.object_id
               JOIN sys.types ty ON ty.user_type_id = c.user_type_id
               WHERE t.is_ms_shipped = 0 AND c.is_computed = 0
                 AND ty.name IN ('nvarchar','varchar','ntext','text','nchar','char','varbinary','binary','image')""")]

    def _metadati_campi(self):
        scelte, tipi = set(), {}
        for modello in apps.get_models():
            for campo in modello._meta.local_fields:
                chiave = (modello._meta.db_table, campo.column)
                tipi[chiave] = campo.get_internal_type()
                if getattr(campo, "choices", None):
                    scelte.add(chiave)
        return scelte, tipi

    # --- identificativi noti: restano in memoria, non escono mai dal processo --------------------
    def _raccogli_identificativi(self, colonne):
        per_tabella: dict[str, set[str]] = {}
        for tabella, colonna, _, _ in colonne:
            per_tabella.setdefault(tabella, set()).add(colonna)
        forti, cognomi = set(), set()
        for tabella, cols in per_tabella.items():
            minuscole = {c.lower(): c for c in cols}
            if R.TABELLE_PERSONE.search(tabella):
                nome = next((minuscole[c] for c in ("nome", "first_name") if c in minuscole), None)
                cognome = next((minuscole[c] for c in ("cognome", "last_name") if c in minuscole), None)
                if nome and cognome:
                    for n, c in self._righe(f"SELECT {q(nome)}, {q(cognome)} FROM {q(tabella)}"):
                        n, c = str(n or "").strip(), str(c or "").strip()
                        if len(n) >= 2 and len(c) >= 2:
                            forti.update({f"{n} {c}".lower(), f"{c} {n}".lower()})
                        if len(c) >= 5:
                            cognomi.add(c.lower())
            for basso, col in minuscole.items():
                if re.search(r"^ragione_sociale$|codice_fiscale|tax_code|partita_iva|^piva$|iban|telefono|cellulare", basso):
                    for (v,) in self._righe(f"SELECT DISTINCT {q(col)} FROM {q(tabella)} WHERE {q(col)} IS NOT NULL"):
                        v = str(v).strip().lower()
                        if len(v) >= 6:
                            forti.add(v)
        # I valori finti non contano come residui, anche se una persona di prova si chiama cosi'.
        finti = {v.lower() for v in NOMI_FINTI + COGNOMI_FINTI}
        forti = {v for v in forti if not set(v.split()) <= finti}
        return {"forti": self._regex(forti), "cognomi": self._regex(cognomi - finti)}

    @staticmethod
    def _regex(valori):
        if not valori:
            return None
        ordinati = sorted(valori, key=len, reverse=True)
        return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(v) for v in ordinati) + r")(?!\w)", re.IGNORECASE)

    # --- scritture -------------------------------------------------------------------------------
    def _blocca_vincoli(self, tabelle):
        for t in tabelle:
            self._esegui_sql(f"ALTER TABLE {q(t)} DISABLE TRIGGER ALL")
            self._esegui_sql(f"ALTER TABLE {q(t)} NOCHECK CONSTRAINT ALL")

    def _sblocca_vincoli(self, tabelle):
        # Senza WITH CHECK: i riferimenti di tabelle svuotate non bloccano la copia di prova.
        for t in tabelle:
            self._esegui_sql(f"ALTER TABLE {q(t)} CHECK CONSTRAINT ALL")
            self._esegui_sql(f"ALTER TABLE {q(t)} ENABLE TRIGGER ALL")

    def _svuota(self, tabelle, errori):
        fatte = set()
        for t in tabelle:
            try:
                self._esegui_sql(f"DELETE FROM {q(t)}")
                fatte.add(t)
            except Exception as exc:  # noqa: BLE001 - l'errore va nel riepilogo, senza valori
                errori.append(f"{t}: svuotamento fallito ({type(exc).__name__})")
        return fatte

    def _applica(self, tabella, colonna, azione, lung, sale, errori):
        if azione == R.TIENI:
            return False
        col, tab = q(colonna), q(tabella)
        condizione = f"{col} IS NOT NULL AND DATALENGTH({col}) > 0"
        try:
            if azione == R.BINARIO:
                nullable = self._righe(
                    "SELECT is_nullable FROM sys.columns WHERE object_id = OBJECT_ID(%s) AND name = %s", [tab, colonna]
                )[0][0]
                self._esegui_sql(f"UPDATE {tab} SET {col} = {'NULL' if nullable else '0x'} WHERE {condizione}")
            else:
                self._esegui_sql(f"UPDATE {tab} SET {col} = {espressione(azione, col, lung, sale)} WHERE {condizione}")
            return True
        except Exception as exc:  # noqa: BLE001 - il messaggio del driver puo' citare valori: solo il tipo
            errori.append(f"{tabella}.{colonna}: {azione} fallita ({type(exc).__name__})")
            return False

    def _non_testo(self, errori):
        righe = self._righe(
            """SELECT t.name, c.name, ty.name FROM sys.columns c JOIN sys.tables t ON t.object_id = c.object_id
               JOIN sys.types ty ON ty.user_type_id = c.user_type_id
               WHERE t.is_ms_shipped = 0 AND c.is_computed = 0
                 AND ty.name IN ('date','datetime','datetime2','smalldatetime','decimal','numeric','money','float','real')""")
        for tabella, colonna, tipo in righe:
            col, tab = q(colonna), q(tabella)
            try:
                if tipo in {"date", "datetime", "datetime2", "smalldatetime"}:
                    if R.DATE_PERSONALI.search(colonna):
                        self._esegui_sql(
                            f"UPDATE {tab} SET {col} = DATEFROMPARTS(1960 + ABS(CHECKSUM(NEWID())) % 45, "
                            f"1 + ABS(CHECKSUM(NEWID())) % 12, 1 + ABS(CHECKSUM(NEWID())) % 28) WHERE {col} IS NOT NULL"
                        )
                elif R.TABELLE_IMPORTI.search(tabella):
                    self._esegui_sql(
                        f"UPDATE {tab} SET {col} = ROUND({col} * (0.6 + 0.8 * RAND(CHECKSUM(NEWID()))), 2) WHERE {col} IS NOT NULL"
                    )
            except Exception as exc:  # noqa: BLE001
                errori.append(f"{tabella}.{colonna}: sostituzione fallita ({type(exc).__name__})")

    def _colonne_tenute(self, azioni, svuotate):
        for (tabella, colonna), (azione, lung) in sorted(azioni.items()):
            if azione == R.TIENI and tabella not in svuotate:
                yield tabella, colonna, lung

    def _valori_nei_tenuti(self, azioni, svuotate, sale, errori):
        """Nelle colonne tenute, un indirizzo mail o un campo cifrato non restano mai."""
        for tabella, colonna, lung in self._colonne_tenute(azioni, svuotate):
            col, testo = q(colonna), f"CAST({q(colonna)} AS nvarchar(max))"
            try:
                self._esegui_sql(
                    f"UPDATE {q(tabella)} SET {col} = {espressione(R.TESTO, col, lung, sale)} "
                    f"WHERE {testo} LIKE N'%@%.%' OR {testo} LIKE N'enc1:%'"
                )
            except Exception as exc:  # noqa: BLE001
                errori.append(f"{tabella}.{colonna}: pulizia fallita ({type(exc).__name__})")

    def _correggi_residui(self, azioni, svuotate, indice, sale, errori):
        """Una colonna tenuta con un identificativo noto viene sostituita per intero."""
        corrette = 0
        for tabella, colonna, lung in list(self._colonne_tenute(azioni, svuotate)):
            if self._conta_colonna(tabella, colonna, indice)[0]:
                azioni[(tabella, colonna)] = (R.TESTO, lung)
                if self._applica(tabella, colonna, R.TESTO, lung, sale, errori):
                    corrette += 1
        return corrette

    def _conta_colonna(self, tabella, colonna, indice):
        col = q(colonna)
        forti = dubbi = 0
        for (v,) in self._righe(
            f"SELECT DISTINCT CAST({col} AS nvarchar(max)) FROM {q(tabella)} WHERE {col} IS NOT NULL AND DATALENGTH({col}) > 0"
        ):
            v = str(v)
            if (indice["forti"] and indice["forti"].search(v)) or RX_CF.search(v) or RX_IBAN.search(v) or RX_EMAIL.search(v):
                forti += 1
            elif indice["cognomi"] and indice["cognomi"].search(v):
                dubbi += 1
        return forti, dubbi

    def _conta_residui(self, azioni, svuotate, indice):
        """Ricontrolla TUTTE le colonne di testo, comprese quelle sostituite."""
        residui, dubbi = [], []
        for (tabella, colonna), (azione, _) in sorted(azioni.items()):
            if tabella in svuotate or azione == R.BINARIO:
                continue
            forti, incerti = self._conta_colonna(tabella, colonna, indice)
            forti = self._togli_mail_finte(tabella, colonna, forti)
            if forti:
                residui.append(f"{tabella}.{colonna}: {forti} valori")
            if incerti:
                dubbi.append(f"{tabella}.{colonna}: {incerti} valori")
        return residui, dubbi

    def _togli_mail_finte(self, tabella, colonna, forti):
        if not forti:
            return 0
        col = f"CAST({q(colonna)} AS nvarchar(max))"
        finte = self._righe(f"SELECT COUNT(DISTINCT {col}) FROM {q(tabella)} WHERE {col} LIKE N'%@example.invalid'")[0][0]
        return max(0, forti - finte)

    def _accessi(self, password, errori):
        """2FA spento, nessuna password vera, un solo superutente di prova."""
        password = password or secrets.token_urlsafe(12)
        try:
            self._esegui_sql("IF OBJECT_ID('twofa_twofactorpolicy') IS NOT NULL UPDATE twofa_twofactorpolicy SET enabled = 0")
            self._esegui_sql("UPDATE auth_user SET password = N'!anonimizzata'")
            self._esegui_sql(
                "INSERT INTO auth_user (password, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined) "
                "VALUES (%s, 1, N'collaudo', N'Utente', N'Collaudo', N'collaudo@example.invalid', 1, 1, SYSUTCDATETIME())",
                [make_password(password)],
            )
            self.stdout.write(f"Accesso: utente collaudo, password {password}")
        except Exception as exc:  # noqa: BLE001
            errori.append(f"accessi: {type(exc).__name__}")
