# `registro_ofi` — Registro OFI / NC (MOD.174)

Area **Qualità** · URL `/ofi-registro/` · codice [`django_app/registro_ofi/`](../../django_app/registro_ofi/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Registro OFI / NC**: modulo dedicato alle opportunità di miglioramento e alle non conformità del sistema di gestione, fedele al MOD.174 - SGI Registro OFI_NC Rev.0. Dashboard, registro MOD.174, «Le mie voci», scheda della voce con PDCA guidato, evidenze, cronologia e collegamenti a audit interni, audit degli enti, specifiche (MOD.133), catalogo processi e azioni correttive MT CN 11.

## Pagine

| URL | Rotta | Cosa fa | Permesso |
|---|---|---|---|
| `/ofi-registro/` | `registro_ofi:home` | Dashboard: «Il mio lavoro» per tutti; a chi consulta il registro numeri chiave, scadute / in scadenza 30 gg / senza responsabile, origine, voci per processo del catalogo, andamento, analisi e attività recente | `registro_ofi.mie.view` (la vista mostra il resto solo con `registro_ofi.registro.view`) |
| `/ofi-registro/elenco/` | `registro_ofi:lista` | Registro MOD.174 con filtri (anche origine, processo, `in_scadenza`, `senza_responsabile`) ed export Excel | `registro_ofi.registro.view` |
| `/ofi-registro/mie/` | `registro_ofi:mie` | Voci di cui si è responsabili | `registro_ofi.mie.view` |
| `/ofi-registro/<id>/` | `registro_ofi:dettaglio` | Scheda: collegamenti, PDCA, evidenze, cronologia | `registro_ofi.mie.view` + vista: registro o responsabile |
| `/ofi-registro/nuovo/` (`?processo=<id>`) | `registro_ofi:nuovo` | Inserimento, precompilato dal processo | `gestione_specifiche.registroofi.add` |
| `/ofi-registro/<id>/modifica/` | `registro_ofi:modifica` | Modifica | `gestione_specifiche.registroofi.add` |
| `/ofi-registro/<id>/avanza/`, `/riapri/`, `/allegati/…` | | PDCA ed evidenze | `registro_ofi.mie.view` + vista: gestore o responsabile |
| `/ofi-registro/cruscotto/` | `registro_ofi:cruscotto` | Vecchio indirizzo: porta alla dashboard con gli stessi filtri | `registro_ofi.registro.view` |
| `/ofi-registro/guida/` | `registro_ofi:guida` | Guida d'uso (anche PDF `?pdf=1`) | `registro_ofi.mie.view` |

## Collegamenti con gli altri moduli

- **Dati**: le tabelle restano in `gestione_specifiche` (`RegistroOFI`, `RegistroOFIEvento`, `RegistroOFIAllegato`, servizio `gestione_specifiche/registro_ofi.py`) per continuità con MOD.133 e `AzioneOFI`; questa app contiene viste, template, permessi e i collegamenti (`collegamenti.py`).
- **Catalogo processi** (`RegistroOFI.processo_sgi` → `sistema_gestione.Processo`, migrazione `gestione_specifiche 0016`): valorizzato dal salvataggio della voce quando «Processo/area» indica un solo processo (codice, nome, «codice - nome» o codice in testa), dal form («Processo del catalogo», che propone anche il responsabile del processo), dalla scheda del processo (`?processo=<id>`) e dai rilievi degli audit interni (processo della domanda di checklist o unico processo dell'audit). La migrazione collega le voci esistenti con lo stesso criterio. La scheda processo ha la scheda «OFI / NC»; `rilievi_esterni_per_processo` usa il processo collegato per la priorità degli audit (regola `priorita-v3`).
- **Origine** (`collegamenti.origine`): rilievo dell'audit interno (`AuditEsito`), audit dell'ente (`AuditEsterno`), riga MOD.133 (`RigaMOD133`), altrimenti «inserita a mano».
- **CAR MT CN 11**: `sistema_gestione:procedura_car` dalla scheda; con CAR aperta la voce si chiude chiudendo la CAR.

## Permessi e deploy

- `registro_ofi/acl_bootstrap.py` (cache `registro_ofi_acl_bootstrap_v1`): permessi `registro_ofi.registro.view` e `registro_ofi.mie.view`, binding di tutte le rotte `registro_ofi:*` (tolti dal bootstrap di `gestione_specifiche`), voce di menu `ofi_registro` → `registro_ofi:home`. Al primo avvio `registro.view` copia i grant attivi di ruolo, utente e gruppo di `gestione_specifiche.specifica.view` (che prima apriva il registro); `mie.view` va a tutti i ruoli. Solo creazione: le modifiche in Admin › ACL restano.
- Deploy: `migrate` (gestione_specifiche 0016), riavvio del sito (il bootstrap gira all'avvio), `collectstatic` non necessario (nessun file statico nuovo).
- Registro attività: le azioni restano sotto il modulo `gestione_specifiche` (`registro_ofi_*`), come prima.

## Guide

- In-app: `sistema_gestione/guida.py` (`GUIDA_OFI`, capitoli `ofi-*`, `PAGE_HELP` per ogni rotta).
- Centro guide: `core/guide_moduli/contenuti/registro_ofi.py`.
