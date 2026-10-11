# Verifica indipendente prompt 01–08 — 2026-10-11

Contratto dei requisiti: [VERIFICA_PROMPT_01-08_requisiti.md](VERIFICA_PROMPT_01-08_requisiti.md). Fonte dei requisiti: `md upgrade moduli/01…08_*.md` (09/10/2026).

**Riferimenti.** La verifica è partita su `origin/main` = `1f2c73c2` e `origin/release/prod` = `bc51d009`. **Mentre era in corso** (11/10 alle 11:22) un'altra sessione ha unito il prompt 06 in `main` (`6aa9cf45`) e promosso P05 + P06 in `release/prod` (`02bae987`). Gli stati "Dove" qui sotto si riferiscono ai ref di oggi. P06 è stato verificato su `6aa9cf45`.

**Metodo.** Per ogni prompt un subagent in sola lettura ha verificato i requisiti con `file:riga` e test. Poi l'auditor ha:
- ricontrollato di persona ogni MANCANTE e DIVERSO significativo e tutti i finding di sicurezza (vedi §8);
- eseguito i test-prova in serie, un worktree alla volta, con un DB SQLite a nome fisso. La deviazione dal metodo del mandato è motivata dal vincolo di risorse di `CLAUDE.md`: la creazione del DB richiede circa 20 minuti.

## 1. Sintesi

| Prompt | FATTO | Dove | Problema più grave |
| --- | --- | --- | --- |
| 01 Contatori/SNMP | 48% | main + release/prod | Bug fattura (A) e andamento reparti (B) **mai riprodotti né corretti**: l'analisi esclude ancora le macchine disattivate e nasconde le letture mancanti |
| 02 SOC | 74% | **solo branch** `feature/soc-autoresolve-cve` | Una regola appresa intercetta anche gli eventi "completed": il backup rientrato non chiude più l'alert (MEDIA, confermato) |
| 03 Anagrafica elenco/admin | 3% (solo D, fatto da P04) | — | **Lavoro mai iniziato**: nessun branch, commit, WIP o stash |
| 04 Mansioni di rischio | 72% | main + release/prod | Migrazioni scritte prima di qualsiasi approvazione dello schema (STOP-1); timeline che rivela "deroga" senza permesso visite |
| 05 E-learning | 50% | main + release/prod (dal 11/10) | Il discente non può scaricare il proprio attestato; pagina di verifica non pubblica; nessun nh3 |
| 06 Asset | 67% | main + release/prod (dal 11/10) | Storico senza MAC e senza dati tecnici; KPI della scheda che diventano ancora "—"/0 muti nel TCO |
| 07 Timbri | 9% | main + release/prod | **Non è il rifacimento**: è un restyling. Backup pre-reset incompleto + bypass del permesso copia (ALTA, confermati) |
| 08 Audit interni | 0% di lavoro del prompt | — | **Lavoro mai iniziato**; quello che esiste è precedente (25–29/09) |

## 2. Cruscotto

FATTO comprende i requisiti con codice e test. Le righe N/A (regole non applicabili perché manca il lavoro) sono escluse dai conteggi.

| Prompt | Requisiti | FATTO | FATTO SENZA TEST | PARZIALE | MANCANTE | DIVERSO | NON VERIF. | Branch | In main | In release/prod |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 52 | 25 | 3 | 13 | 7 | 3 | 1 | `contatori-dashboard-menu`, `contatori-wizard-snmp` (`contatori-ux-wizard` vuoto) | sì | sì |
| 02 | 42 | 31 | 0 | 4 | 1 | 4 | 2 | `soc-autoresolve-cve` | **no** | **no** |
| 03 | 30 | 1 | 1 | 1 | 24 | 2 | 1 | nessuno | — | — |
| 04 | 50 | 36 | 1 | 10 | 2 | 0 | 1 | `anagrafica-mansioni-rischio` | sì | sì |
| 05 | 42 | 21 | 6 | 9 | 1 | 2 | 3 | `anagrafica-elearning-pro` | sì | sì |
| 06 | 39 | 26 | 3 | 8 | 0 | 0 | 2 | `assets-qr-mfc-storico` | sì (11/10) | sì (11/10) |
| 07 | 34 | 3 | 0 | 12 | 16 | 1 | 2 | `timbri-rifacimento`, `specifiche-timbri-propri` | sì | sì |
| 08 | 19 | 1* | 0 | 10* | 5 | 3* | 0 | nessuno | — | — |

\* P08: tutto preesistente al prompt (commit del 25–29/09), nessuna riga è lavoro del prompt.

**Test eseguiti dall'auditor** (con `--keepdb`, DB a nome fisso, `DEFAULT_FROM_EMAIL` sintetico):

| Prompt | Ref | Test | Esito |
| --- | --- | --- | --- |
| 01 | `1f2c73c2` | 109 (wizard, errori, cruscotto, permessi, AnalisiTest, fattura_import) | **OK** |
| 02 | `b75a1a12` | 197 (learned_suppression, automation_registry, cve_impact, docs_render, cases, rule_simulation, analisi_risposta, view_acl, config_acl, soc) | **OK** |
| 03 | — | nessun lavoro | — |
| 04 | `1f2c73c2` | 284 (mansioni_rischio_b, upload, a1/a2, assegnazioni, referti, libretto, scadenze, schede_sicurezza) | **OK** |
| 05 | `1f2c73c2` | 111 (elearning_sicurezza, pro, fase2, elearning, reminders) | **OK** |
| 06 | `6aa9cf45` | 340 (asset_qr, mfc_stats, storico_asset, report_catalog, it_infrastructure, security, routing, tickets allegati, contatori ×4) | **OK** |
| 07 | `1f2c73c2` | 83 (timbri, mpq_timbri, gestione_specifiche AdminSectionTest) | **OK** (8 skipped) |
| 08 | — | nessun lavoro | — |

Nessun test rosso, quindi nessun confronto necessario con la baseline `03d40003`.

**Controlli trasversali su `origin/main`:**
- `check` pulito su `1f2c73c2`, `6aa9cf45` e sul branch P02.
- `makemigrations --check --dry-run`: *No changes detected* su `1f2c73c2`, `6aa9cf45` e sul branch P02.
- `acl_fallback_report --only-unbound` sul DB di test, dopo `bootstrap_acl_v2 --apply`: 85 route senza binding, tutte `_` (core) o `admin_portale`. **Nessuna** di contatori, anagrafica, timbri, gestione_specifiche o assets. Limite: il bootstrap crea binding su tutte le route, quindi il report non dimostra che in produzione esistano i binding delle route nuove. P02 e P04 dipendono da binding a prefisso o copiati da route sorelle presenti nel DB di produzione (§4).
- `git grep "import sniff_mime" origin/main`: **vuoto**. Restano solo due commenti, a `anagrafica/views.py:11213` e `tests_upload_documenti.py:2`; il codice usa `sniff_upload_mime`, che esiste.
- `|safe` nei file toccati: solo `{{ verifica_qr_svg|safe }}` in `attestato_formazione*.html` (SVG del QR generato dal server, non dati utente): accettabile.
- `except Exception:` + `pass`/`continue` **aggiunti** dai merge: 5, tutti in P04:
  - `integrita_scadenze.py`
  - `mansioni_rischio_admin.py:74`
  - `notifiche_cambio_mansione.py:47`
  - `anagrafica_extras.py`
  - `views_mansioni_rischio.py:126`

  P01, P02, P05, P06 e P07 non ne aggiungono.
- Previsione dei conflitti (`git merge-tree`):

  | Merge previsto | Conflitti |
  | --- | --- |
  | main + P02 | solo `CHANGELOG.md` |
  | main + `anomalie-decisioni-operatore` | solo `CHANGELOG.md` |
  | P02 + P06 | solo `CHANGELOG.md` |

  Prima del merge di P06 il conflitto era anche su `docs/AUTOMAZIONI.md` e `docs/moduli/contatori.md`: è stato risolto dall'altra sessione.
- Collisioni di numero nelle migrazioni: **nessuna**.

  | Prompt | Migrazioni |
  | --- | --- |
  | P01 | contatori 0028–0030 |
  | P02 | security 0020 |
  | P04 | anagrafica 0139–0144 |
  | P05 | anagrafica 0145–0156 (catena lineare da 0144) |
  | P06 | assets 0124–0126 |
  | P07, P03, P08 | nessuna migrazione |

## 3. Tabelle complete per prompt

Prova = `file:riga` del codice / test (`Classe::test`). Percorsi relativi a `django_app/`.

### P01 — Contatori/SNMP

| ID | Stato | Dove | Prova | Note |
| --- | --- | --- | --- | --- |
| A1 | MANCANTE | — | `fattura_import.py` e `views.py:168-216` non toccati dopo il 06/10 | Nessun test rosso, nessuna traccia di riproduzione |
| A2 | PARZIALE | preesistente | `tests_fattura_import::LeggiFatturaTests::test_xml`, `test_pdf_con_riga_a_cavallo_di_pagina`, `test_p7m_e_formati_ignoti`, `InterpretaTests::test_xml_con_doctype_rifiutato` | Mancano PDF scansionato, vuoto, `1.234,56`, date, più righe stessa macchina, duplicato |
| A3 | PARZIALE | preesistente | `fattura_import.py:66,76,95,149,166,183,193` | Messaggi generici; numero/data mancante è solo un avviso (`:221-222`) |
| A4 | PARZIALE | preesistente | `views.py:171-192` | Anteprima sì, ma nessuna associazione manuale delle righe non assegnate |
| A5 | DIVERSO | preesistente | `models.py:662-664` `unique_together=("numero","trimestre")` | Non numero+fornitore+data, nessun avviso: non accettabile |
| A6 | PARZIALE | preesistente | `fattura_import.py:71-76` defusedxml; `views.py:177` 5 MB | Manca il limite di pagine PyMuPDF (`:63-64`) |
| B1 | MANCANTE | — | `services.py:254-305` non toccato | "Accantonato" |
| B2 | FATTO | preesistente | `tests.py::AnalisiTest::test_consumo_delta_q2_e_anomalia` | |
| B3 | FATTO | preesistente | `services.py:296-298`; stesso test | |
| B4 | MANCANTE | — | `Macchina.reparto` CharField corrente (`models.py:280`) | Nessuno storico reparto |
| B5 | MANCANTE | — | `services.py:293-299` | Letture mancanti confluite in silenzio (ricontrollato) |
| B6 | MANCANTE | — | `services.py:257,270` `macchina__attiva=True` | Disattivare una macchina ne cancella lo storico dall'analisi (ricontrollato) |
| B7 | FATTO SENZA TEST | preesistente | ordinamento `YYYY-Qn` | |
| B8 | MANCANTE | — | — | Nessun test grafico = xlsx |
| B9 | PARZIALE | main | `tests_cruscotto::StatoFlottaTests::test_query_della_centrale_non_crescono_con_la_flotta` | Solo la dashboard; N+1 di `riconcilia` non coperto |
| C1 | FATTO | main | `services.py:945-991`; `StatoFlottaTests::test_conteggi_esclusivi` | N=3 fisso |
| C2 | FATTO | main | `ConsumabiliFiltroTests::test_filtro_critici` | Conteggio e filtro con funzioni diverse |
| C3 | FATTO SENZA TEST | main | `services.py:1156` | |
| C4 | FATTO | main | `FattureDaRiconciliareTests::test_solo_trimestri_con_problemi` | |
| C5 | FATTO | main | `StatoFlottaTests::test_ultimi_errori_con_causa` | |
| C6 | PARZIALE | main | `dashboard.html:45-54` | Fatture → solo il primo trimestre |
| C7 | FATTO | main | `MenuRaggruppatoTests::test_gruppi_e_configurazione_solo_per_gestione` | |
| C8 | PARZIALE | main | `SchedaInfoTests` | I test non asseriscono modello, asset, reparto, storico |
| D1 | FATTO | main | `wizard.py:48-208`; `PassiTests::test_indietro_non_perde_i_dati` | I vecchi form restano attivi |
| D2 | FATTO | main | `CorrezioniReviewTests::test_riconoscimento_da_oid_dedicato_…` | |
| D3 | FATTO | main | `PassiTests::test_indirizzo_non_valido_snmp_001`, `test_v3_richiede_utente` | |
| D4 | FATTO | main | `PassiTests::test_credenziali_obbligatorie_e_segreto_cifrato_in_sessione` | |
| D5 | FATTO | main | `git grep novicromprinter`: solo `migrations/0002` (ricontrollato); `NessunaCommunityPredefinitaTests` | Il valore nel DB di produzione resta |
| D6 | FATTO | main | `TestConnessioneTests::test_timeout_snmp_003_con_un_retry`, `test_avanti_bloccato_senza_test` | |
| D7 | FATTO | main | `MappaturaEConfermaTests::test_mappatura_evidenzia_oid_assenti_…` | |
| D8 | PARZIALE | main | `forms_wizard.py:109-122` | Reparto testo libero |
| D9 | FATTO | main | `BozzaTests::test_bozza_non_verificata_visibile` | |
| D10 | FATTO | main | `tests_wizard_altri` (Macchina, Profilo, Colonna, Sonda) | |
| D11 | FATTO | main | `tests_wizard_dispositivo` | |
| E1–E6 | FATTO (6) | main | `errori_snmp.py:31-47`; `tests_errori_catalogo` | |
| E7 | PARZIALE | main | `dashboard.html:61-64` | La dashboard mostra il testo grezzo, senza catalogo |
| REG-ACL | FATTO | main | `migrations/0030_acl_wizard_generici.py`; `MigrazioneAclTests::test_tutte_le_route_del_modulo_sono_coperte` | |
| REG-JSON | FATTO | main | `WizardSondaTests::test_sola_consultazione_403_json` | |
| REG-UPLOAD | DIVERSO | — | nessun upload nuovo | N/A |
| REG-SAFE | FATTO SENZA TEST | main | nessun `|safe` | |
| REG-EXC | PARZIALE | main | `snmp.py:437-446` preesistenti non corretti | |
| REG-MIG | PARZIALE | main | 0028–0030 | Il reverse della 0030 non ripristina i binding della 0029 |
| REG-DOC | PARZIALE | main | `docs/moduli/contatori.md:22` | URL del wizard inesistente |
| REG-BUMP | MANCANTE | — | VERSION 1.6.1 nei merge | |
| REG-GIT | DIVERSO | — | nomi branch diversi; `contatori-ux-wizard` vuoto | Percorso dei merge rispettato |
| STOP-1 | NON VERIFICABILE | — | nessuna richiesta del file fattura tracciata | |
| STOP-3 | PARZIALE | — | 26f50fe3: +2705 nette, un solo merge | Nessuna proposta di split |

### P02 — SOC (branch `feature/soc-autoresolve-cve`, `b75a1a12`)

| ID | Stato | Prova | Note |
| --- | --- | --- | --- |
| A1 | FATTO | `services/learned_suppression.py:49-99`; `FingerprintTests` (4) | L'impronta **non include lo stato dell'evento** (vedi bloccante B2) |
| A2 | FATTO | `alert_lifecycle.py:46-95`; `LearningTests::test_resolved_and_automatic_closures_do_not_count`, `test_dismissal_without_reason_does_not_count` | |
| A3 | DIVERSO (più severo) | `learned_suppression.py:258-305`; `test_third_dismissal_creates_exact_learned_rule_with_audit` | Serve almeno una disattivazione di un utente con permesso config |
| A4 | PARZIALE | audit testato | Notifica al canale SOC senza test |
| A5 | FATTO | `rule_engine.py:20-23,62-70`; `test_fourth_occurrence_is_suppressed_with_trace` | |
| A6 | FATTO | `learned_suppression.py:110-198`; `GuardrailTests` (6) | Ransomware solo da keyword; guardrail disattivabili da UI |
| A7 | FATTO | `GuardrailTests::test_escalated_severity_still_alerts` | |
| A8 | FATTO | `GuardrailTests::test_manual_reopen_disables_rule_and_resets_count` | |
| A9 | FATTO | `views_suppressions.py`; `ViewTests::test_suppressions_page_filters_and_revoke` | |
| A10 | FATTO | `test_two_dismissals_do_not_create_rule_and_badge_warns` | |
| A11 | PARZIALE | `soc_settings.py:66-86` | Severità escluse = solo booleano; tipi esclusi non testati |
| B1 | FATTO | `auto_resolution.py:56-77,460-486`; `RegistryTests` | Test esistenti intatti |
| B2 | DIVERSO (accettabile) | `VpnRuleTests`, `CvePatchedRuleTests` | "Heartbeat" = regola storica rinominata |
| B3 | FATTO | `test_existing_rule_writes_rule_code_and_evidence` | ID della prova solo in timeline |
| B4 | DIVERSO | `auto_resolution.py:501-518`; `SimulationTests` | **Non riusa `rule_simulation.py`** |
| C1 | DIVERSO (accettabile) | `software_inventory.py:88-251`; `InventoryImportTests` | Nessun preset predefinito (coerente con STOP-1) |
| C2 | FATTO | `test_import_is_idempotent`, `test_preview_reports_skipped_rows_with_reason` | |
| C3 | FATTO | `models.py:1319-1383`; `test_missing_software_marked_not_deleted` | |
| C4 | FATTO | `test_alias_applies_on_import` | UI non testata |
| C5 | PARZIALE | `cve_feeds.py:308-329` | `suggest_cpe` non testato |
| C6 | FATTO | `FeedTests::test_enrichment_parses_nvd_kev_epss_and_caches` | Spento di default |
| C7 | FATTO | idem; `test_epss_cache_key_is_hashed` | |
| C8 | FATTO | `SecurityExternalFeedCache`; `test_api_key_encrypted_and_sent` | |
| C9 | FATTO | `test_retry_with_backoff_then_error`, `test_rate_limiter_waits_after_limit` | Rate limit solo per NVD |
| C10 | FATTO | `MatchingTests::test_matching_case_table` | |
| C11 | FATTO | `VersionCompareTests::test_compare_table` | |
| C12 | PARZIALE | `templatetags/security_cve.py` | Non c'è sul `SecurityVulnerabilityFinding` (nessuna pagina) |
| C13 | FATTO | `test_kev_or_critical_never_proposed_for_closure` | |
| C14 | FATTO | `ViewTests::test_hub_asset_page_shows_vulnerabilities` | |
| C15 | FATTO | `MatchingTests::test_dashboard_lists` | Ordinamento con una sola CVE |
| C16 | FATTO | `FeedTests` con mock | |
| REG-ACL | NON VERIFICABILE | `urls_hub.py`; check nelle view | **Nessun binding creato** per le route nuove: dipende dai prefissi `/soc/` nel DB di produzione |
| REG-JSON / UPLOAD / SAFE / EXC / MIG / DOC / GIT | FATTO (7) | `views_vuln.py:113-134`; `security/0020` | Migrazione auto-reversibile, `makemigrations --check` pulito sul branch |
| REG-BUMP | MANCANTE | — | |
| STOP-1 | FATTO | mappatura configurabile | |
| STOP-2 | NON VERIFICABILE | — | Guardrail critico/KEV spegnibili da UI senza traccia di decisione |

### P03 — Anagrafica elenco/admin

Nessun lavoro. Per verificarlo: pickaxe `-S VistaElenco/PreferenzaVistaUtente/colonne_elenco` su tutta la storia, grep su 40 ref, 24 worktree e 7 stash. Risultato vuoto, ricontrollato dall'auditor.

| ID | Stato | Note |
| --- | --- | --- |
| A1–A9 | MANCANTE (9) | Nessun registro colonne, modello o preset |
| B1–B4, B7, B8, B10 | MANCANTE (7) | `dipendente_create` resta un form unico |
| B5 | DIVERSO | Coperto in parte dall'audit sicurezza (`core/legacy_utils.py:350-361`, `core.tests.LegacySyncHardeningTests`), non da P03 |
| B6 | DIVERSO | Allowlist solo al login/SSO (`core.test_security_audit_fase2.LdapGroupAllowlistLoginTests`) |
| B9 | NON VERIFICABILE | Nessuna scrittura LDAP nel codice, ma niente da attribuire a P03 |
| C1–C5 | MANCANTE (5) | |
| D1 | PARZIALE (fatto da P04) | `anagrafica_extras.py:427-470` | Conteggi solo su 2 gruppi, ordine fisso |
| D2 | FATTO SENZA TEST (P04) | `anagrafica_extras.py:489-509` |
| D3 | FATTO (P04) | `tests_mansioni_rischio_b::PagineMansioniRischioTests::test_subnav_raggruppata_con_voce_accesa` |
| REG-WT / DOC / GIT | MANCANTE (3) | Nessun lavoro |

### P04 — Mansioni di rischio

| ID | Stato | Prova | Note |
| --- | --- | --- | --- |
| A1 | PARZIALE | `MotoreMansioniRischioTests::test_campi_legacy_ignorati_…` | Il form legacy modifica ancora i campi deprecati col gate formazione |
| A2 | FATTO | `models_mansioni_rischio.py:43-100` | Periodicità su `TipoVisitaMedica` |
| A3 | FATTO | `:103-129` | Ordine e note senza test |
| A4 | FATTO | `test_override_aggiunta_ed_esclusione`, `test_motivo_override_obbligatorio` | |
| A5 | FATTO | `mansionario.py:327-507`; `test_requisiti_dalla_mansione_di_rischio_con_provenienza` | a1/a2 verdi (eseguiti) |
| A6 | FATTO | `test_export_organigramma` | Filtro per fattore non testato |
| A7 | FATTO | `test_form_anteprima_non_salva_e_salvataggio_accoda` | |
| B1 | FATTO | `CambioMansioneTests::test_cambio_semplice_con_rischi_in_piu_e_in_meno` | |
| B2 | PARZIALE | — | Nessuna deduzione area/reparto → mansione |
| B3 | FATTO | `RiallineamentoMassivoTests::test_cinquanta_dipendenti_idempotente` | Report solo in AuditLog |
| B4 | FATTO | `OverrideRiallineamentoTests` | |
| B5 | FATTO | `test_programmato_poi_annullato`, `test_cambio_retroattivo_e_stato_operativo` | |
| B6 | FATTO | `test_rigenerazione_chiude_come_non_piu_dovuto` | DPI senza test dedicato |
| B7 | FATTO | `test_doppia_esecuzione_idempotente`, `test_notifica_dopo_il_commit_senza_dati_clinici` | |
| B8 | FATTO | `test_stato_operativo_su_scadenzario_e_cruscotto` | Organigramma senza test |
| B9 | PARZIALE | — | Nessun ricalcolo al cambio protocollo |
| B10 | PARZIALE | `test_visita_del_tipo_sbagliato_non_chiude` | La voce generica si chiude con qualsiasi visita |
| B11 | PARZIALE | `test_prescrizioni_nel_contesto_della_mansione_solo_con_permesso` | Contesto = mansione attuale, non quella di destinazione |
| B12 | FATTO | `StatoOperativoTests::test_non_idoneita_blocca_sempre` | |
| B13 | PARZIALE | `test_integrita_segnala_e_pubblica_in_monitoring` | Mancano "requisiti senza adempimento" e "visite scadute" |
| B14 | FATTO | `services/eventi_sicurezza.py` | |
| T1–T11 | FATTO (11) | `tests_mansioni_rischio_b` (eseguiti) | T10 usa un superuser con mock |
| MIG1 | FATTO | `migra_mansioni_rischio` (dry-run, `--apply`, `--rollback`, `--report`); `MigrazioneDatiTests` | |
| MIG2 | FATTO | solo aggiunte | |
| SEC1 | PARZIALE | `exports_sicurezza.py` | Timeline "Deroga concessa" visibile a tutti |
| SEC2 | PARZIALE | `notifiche_cambio_mansione.py` | Il job notturno pubblica in monitoring le righe "visite" con il tipo di visita |
| SEC3 | FATTO | `core/download_security.py:83-107`; `RefertiDownloadSicuroTests` (4) | "Sostituisci" in `referto_gestione` accetta DOC/XLS |
| STOP-1 | MANCANTE | wip `33013a89` contiene già 0139–0141 | Nessuna traccia di approvazione dello schema |
| STOP-2 | FATTO | `ConfigSicurezzaOperativa`; `DecisioniDerogaEProtocolloTests` | |
| REG-WT | NON VERIFICABILE | | |
| REG-ACL | PARZIALE | `0142_mansioni_rischio_acl.py` | `dipendente_sicurezza_panel` solo `@login_required` (ricontrollato) |
| REG-JSON | FATTO SENZA TEST | | |
| REG-UPLOAD / SAFE / MIG / DOC / VIEWS / GIT | FATTO (6) | | |
| REG-EXC | PARZIALE | 5 `except Exception: pass` nuovi | |
| REG-BUMP | MANCANTE | | |

### P05 — E-learning

| ID | Stato | Prova | Note |
| --- | --- | --- | --- |
| A1 | PARZIALE | `views_elearning.py:57-124` | Niente tempo residuo; **attestato non scaricabile dal discente** (`views.py:2897`, ricontrollato) |
| A2 | PARZIALE | `ModuliEVersioniTests::test_indice_per_moduli_nel_player` | PDF convertito in PNG, non incorporato |
| A3 | FATTO SENZA TEST | `views_elearning.py:142-148` | |
| A4 | NON VERIFICABILE | | Serve la prova a 375 px |
| A5 | FATTO | `QuizTokenTests::test_estrazione_casuale_e_set_servito` | |
| A6 | FATTO | `test_attesa_tra_tentativi`, `test_tentativi_esauriti_e_sblocco_hr` | |
| A7 | FATTO | `test_feedback_per_domanda_solo_a_quiz_superato` | |
| A8 | FATTO | `DomandeTipizzateTests` | |
| A9 | DIVERSO | `VerificaAttestatoTests::test_pagina_minima_e_solo_autenticati` | Solo per autenticati; mostra anche protocollo e scadenza |
| A10 | FATTO | `GradimentoEfficaciaTests` | |
| B1 | FATTO | `ImportInBackgroundTests`, `ElearningImportTests` | |
| B2 | FATTO | `ImportDomandeExcelTests` | |
| B3 | FATTO | `ModuliEVersioniTests::test_nuova_versione_solo_dopo_un_completamento` | |
| B4 | FATTO | `AssegnazioniAutomaticheTests` | Onboarding senza test |
| B5 | PARZIALE | `ElearningManageTests::test_assegna_crea_assignment` | **Niente assegnazione per gruppi** |
| B6 | FATTO | `run_elearning_assegnazioni` | |
| B7 | FATTO | `ScalettaPromemoriaTests` (6) | Nessun retry dell'email al responsabile |
| C1 | PARZIALE | `elearning_report.py:29-70` | "In scadenza" non distinto |
| C2 | FATTO SENZA TEST | `:73-111` | Ore senza filtro di periodo |
| C3 | PARZIALE | `:86-91` | Tempo di fruizione, non tempo dall'assegnazione al completamento |
| C4 | FATTO | `CruscottoRegistroTests::test_pagine_ed_export` | PDF non testato |
| C5 | PARZIALE | `models_elearning.py:66-91` | **IP/dispositivo assenti**; nessuna rettifica tracciata; `save()` rifirma |
| INT1–INT3 | FATTO (3) | `CompletamentoTests`, `HeartbeatTests`, `test_completamento_una_volta_sola` | Nessuna falsificazione del completamento trovata |
| SEC1 | FATTO | `AccessoTests` | |
| SEC2 | FATTO | `services/elearning_quiz.py:170-188` (ricontrollato); `test_risposte_corrette_mai_nell_html_del_quiz` | |
| SEC3 | DIVERSO | `elearning_markdown.py:42-112` | Renderer escape-first fatto in casa, **non nh3** |
| STOP-1 | NON VERIFICABILE | | Nessun piano MVP tracciato |
| STOP-2 | FATTO | `RegoleFadEPubblicazioneTests`, `PermessoConfermaFadTests` | |
| STOP-3 | FATTO SENZA TEST | nessuno SCORM | |
| REG-WT | NON VERIFICABILE | | |
| REG-ACL / SAFE / EXC | FATTO SENZA TEST (3) | migrazioni 0145, 0148, 0150, 0156 | |
| REG-JSON | PARZIALE | `views_elearning.py:238-239` | Battito con sessione scaduta → 302 |
| REG-UPLOAD / MIG / DOC / GIT | FATTO (4) | | Il reverse di 0146 fallisce con più cicli |
| REG-BUMP | MANCANTE | | Bump arrivato con P06 |
| REG-VIEWS | PARZIALE | `views.py` +234/−297 | Diverse funzioni nuove in `views.py` |
| PERF | PARZIALE | | Il battito fa circa 4 scritture |

### P06 — Asset (verificato su `6aa9cf45`)

| ID | Stato | Prova | Note |
| --- | --- | --- | --- |
| A1 | FATTO | `tests_asset_qr::QrImageAndPanelTests::test_detail_and_list_render_qr_component` | |
| A2 | FATTO | `test_bulk_labels_pdf_has_one_page_per_asset` | Dialog, non popover |
| A3 | FATTO | partial `qr_thumb`/`qr_dialog` | Pagine IT e officina senza test |
| A4 | FATTO | `test_cache_key_changes_with_tag_and_token` | |
| A5 | FATTO | `QrDestinationTests` (6) | |
| SEC1 | FATTO | Token generato solo in `services/asset_qr.py:93,116` (ricontrollato); `test_new_asset_has_no_implicit_public_token` | I token esistenti della 0069 restano |
| SEC2 | FATTO | `test_image_is_png_generated_server_side` | |
| SEC3 | FATTO SENZA TEST | `views.py:2641-2688` | Nessun test di diniego |
| SEC4 | PARZIALE | `AssetImageUploadHardeningTests` | Import Excel senza controllo MIME |
| B1 | PARZIALE | `tests_mfc_stats` | Solo l'ultimo errore SNMP, periodo fisso |
| B2 | FATTO | `test_stampante_non_collegata_propone_le_mfc_candidate` | |
| B3 | FATTO | `ITMonitoringTests::test_inline_mfc_read_now_is_queued_…` | |
| B4 | FATTO | `test_lettura_vecchia_segnalata` | Oltre 60 giorni il messaggio è fuorviante |
| B5 | FATTO | `test_livelli_automatici_senza_snmp_nella_request` | |
| C1 | PARZIALE | `models.py:3999-4053` `AssetFieldHistory` | **MAC e dati tecnici non storicizzati** |
| C2 | FATTO | `VieDiScritturaTests` (6) | Nessuna scrittura da job |
| C3 | FATTO | `test_vista_storico_filtri_e_alla_data`, `test_com_era_alla_data` | |
| C4 | FATTO SENZA TEST | `0125_storico_campi_asset.py:18-62` | |
| C5 | PARZIALE | `ServizioTests` | Permessi testati solo per l'anonimo |
| C6 | FATTO | `test_retention_conserva_l_ultima_voce_di_ogni_campo` | |
| D1–D5 | FATTO (5) | `tests_report_catalog` | Totali testati solo sull'inventario |
| D6 | PARZIALE | `KpiNonDisponibileTests` | `asset_detail.html:1188-1216`: zeri muti nel TCO |
| PERF | PARZIALE | `assertNumQueries(8)` su `monitoring_for_asset` | Manca sulla pagina intera |
| STOP-1 / STOP-2 | NON VERIFICABILE (2) | | Destinazione del QR e report scelti senza traccia |
| REG-WT / JSON / SAFE / MIG / BUMP / VIEWS / GIT | FATTO (7) | | Bump a 1.6.2; exe non verificabile |
| REG-ACL | FATTO SENZA TEST | 0124–0126 | La regex `^/assets/view/\d+/qr` copre anche `qr-label` |
| REG-EXC | PARZIALE | `report_catalog.py:363,383,395` | Fail-closed senza log |
| REG-DOC | PARZIALE | CHANGELOG | `## 1.6.2` inserito sotto `[Unreleased]`: ha inglobato le voci di altre sessioni |

### P07 — Timbri

| ID | Stato | Prova | Note |
| --- | --- | --- | --- |
| A1 | MANCANTE | Solo `RegistroTimbro` (`timbri/models.py:88-182`) | Nessuna migrazione dopo la 0006 |
| A2 | MANCANTE | due booleani + `is_sospeso` | Nessuna state machine |
| A3 | PARZIALE | `views.py:159-196` | Dedup solo in memoria |
| A4 | MANCANTE | | |
| A5 | FATTO (preesistente) | `anagrafica.tests_mpq_timbri.MpqTimbriPropagazioneTests` | La riattivazione azzera la storia |
| A6, A7 | MANCANTE (2) | | |
| B1 | PARZIALE | `views.py:704-744`; `test_stato_filters` | Mancano sospesi, smarriti, quarantena, movimenti |
| B2 | PARZIALE | `test_search_finds_employee_by_stamp_code` | "Chi aveva X il giorno Y" non supportato |
| B3–B6, B8 | MANCANTE (5) | | |
| B7 | PARZIALE | `test_export_xlsx_respects_filters_and_is_audited` | Export dell'elenco, non del registro |
| C1 | PARZIALE | `gestione_specifiche/timbri_views.py:22-45`; `test_applica_timbri_rifiuta_timbro_di_altra_persona` | Registro parallelo `TimbroCapocommessa`, nessun controllo "alla data" |
| C2 | PARZIALE | `timbri_views.py:123-141` | Nessuna timeline del timbro |
| INT1 | PARZIALE | Reset: superuser + conferma + audit, **ma backup incompleto** (ricontrollato) | `cleanup_orphan_operatori` e `operatore_delete` cancellano senza protezioni |
| INT2, INT3 | MANCANTE (2) | `codice_timbro` solo `db_index` | |
| SEC1 | PARZIALE (preesistente) | `core/encrypted_storage.py:49-51` | Non fail-closed |
| SEC2 | MANCANTE | `views.py:1574-1617` (ricontrollato) | Originale servito senza watermark a chi ha `timbri_view` |
| SEC3 | PARZIALE | `forms.py:85-100` | Solo PNG, niente Pillow/metadati/limite pixel |
| MIG | MANCANTE | | |
| STOP-1 | DIVERSO | Analisi `bbeb212a` revertata da `e851c6a3`, poi restyling | |
| STOP-2 | NON VERIFICABILE | CNOT116 nell'analisi, nessuna risposta | |
| REG-WT | NON VERIFICABILE | | |
| REG-JSON | MANCANTE | `operatore_preview` → redirect | |
| REG-UPLOAD / SAFE / EXC | PARZIALE (3) | | |
| REG-DOC | FATTO | | `docs/moduli/timbri.md:22` dice "ACL v2" per permessi legacy |
| REG-BUMP | MANCANTE | | |
| REG-GIT | FATTO | | |

### P08 — Audit interni

Nessun lavoro del prompt: dopo il 09/10 l'unico commit sull'app è `fff20068`, che contiene `services/soa.py` (finding S8). Lo stato attuale, tutto **preesistente** (commit `e525875a`…`6cd61801`, 25–29/09), è questo:

| ID | Stato | Note |
| --- | --- | --- |
| A1 | PARZIALE | Solo programma annuale, senza reclami né requisiti cliente |
| A2 | PARZIALE | Matrice sì, calendario no, nessun "non auditato da N mesi" |
| A3 | DIVERSO | Il conflitto blocca sempre, nessuna deroga (scelta MT CN 12); qualifica senza scadenza |
| B1 | PARZIALE | Form a gruppi, nessuna domanda dai rilievi precedenti |
| B2 | DIVERSO | `.ics` costruito a mano, non `meeting_outlook.py`; nessuna conferma |
| B3 | FATTO | "Testo generato dall'AI locale: va verificato" |
| C1 | PARZIALE | Autosave sì; nessuna distinzione NC maggiore/minore; niente fotocamera |
| C2 | PARZIALE | Nessun retry né coda locale |
| C3 | PARZIALE | Mancano maggiore/minore e osservazione |
| D1 | DIVERSO | NC e OFI → Registro OFI MOD.174, **nessuna integrazione con `anomalie`** |
| D2 | PARZIALE | Causa in testo libero |
| D3 | MANCANTE | Nessun sollecito; la chiusura non verifica le azioni |
| E1 | PARZIALE | Nessun hash del rapporto, nessun export xlsx |
| E2 | PARZIALE | Nessun cruscotto in-app |
| SEC | PARZIALE | Nessun ruolo auditato: chi ha `audit.view` vede tutti i rilievi |
| STOP-1 | MANCANTE | Nessuna gap analysis |
| REG-WT / DOC / GIT | MANCANTE (3) | |

## 4. Bloccanti prima di release/prod e del deploy

P01, P04, P05, P06 e P07 sono **già in `release/prod`** ma, per quanto noto, non ancora deployati: i bloccanti valgono quindi per il **pacchetto**.

**Sicurezza (confermati di persona):**
1. **P07, ALTA.** Il backup prima del reset del registro è incompleto:
   - `_backup_registro_csv` (`timbri/views.py:379-391`) usa `export_timbri_csv`, che **salta ogni registro senza `sharepoint_item_id`** (`management/commands/export_timbri_csv.py:84-87`);
   - poi `reset_timbri_table` cancella tutto (`:404-406`).

   I registri creati nel portale si perdono senza copia.
2. **P07, ALTA.** Il permesso "copia/download" si aggira: `serve_timbri_image` senza `?copy`/`?download` restituisce l'**originale a piena risoluzione** a chi ha `timbri_view` (`timbri/views.py:1578-1617`). Il commit `6416affe` dichiara "permesso copia lato server".
3. **P02, MEDIA (blocca il merge).** `learned_rule_matches` non guarda lo stato dell'evento (`learned_suppression.py`), e `evaluate_security_rules` sopprime prima di `_evaluate_backup` (`rule_engine.py:18-21`). Effetto: dopo 3 disattivazioni di un job di backup, anche gli eventi "completed" vengono soppressi e `resolve_backup_recovered` non chiude più gli alert aperti. Nessun test lo copre.
4. **P01, MEDIA.** Il test di connessione del wizard invia la community salvata o globale a qualunque IP scelto da chi ha il permesso di gestione (`contatori/wizard.py:261-275,307-324`). Con v1/v2c viaggia in chiaro.
5. **P04, MEDIA privacy.**
   - La timeline del pannello sicurezza mostra "Deroga concessa…" a chi non ha il permesso visite (`sicurezza_panel.html:143`).
   - `run_integrita_sicurezza` pubblica in monitoring le righe "visite" con il tipo di visita per persona (`integrita_scadenze.py:126-127`).
6. **P04, MEDIA-BASSA.** `dipendente_sicurezza_panel` ha solo `@login_required` (`views_mansioni_rischio.py:257`, ricontrollato). Con lo strict attivo in produzione, una route senza binding è **negata**, quindi non c'è esposizione; ma chi ha il permesso della route sorella `dipendente_conformita_panel` vede il pannello di qualsiasi `legacy_id`.
7. **Rischio preesistente rilevato da P03, MEDIA.** `dipendente_create` collega il nuovo dipendente al primo `UtenteLegacy` la cui email **inizia per** `alias@`, senza conferma, senza controllo staff/superuser e senza audit (`anagrafica/views.py:1075-1080`, ricontrollato).

**ACL da verificare sul DB di produzione prima del deploy:**
- P02 non crea binding per `/soc/soppressioni/`, `/soc/vulnerabilita/`, `/soc/admin/config/automatismi|inventario|software/`.
- P04 e P05 copiano i binding da route sorelle solo se queste ne hanno uno.

Eseguire `acl_coverage_report --only-unbound` sul DB di destinazione.

**Migrazioni:**
- Nessuna collisione.
- Reverse imperfetti, da conoscere in caso di rollback:
  - contatori 0030 non ripristina i binding della 0029;
  - anagrafica 0140 si ferma se ci sono orfani;
  - anagrafica 0146 fallisce con più cicli e-learning.

**Test rossi nuovi:** nessuno, sui 1.124 test eseguiti.

**Decisioni prese senza traccia di una domanda a Brizio:**
- **P04 STOP-1:** le migrazioni 0139–0141 sono nel commit wip `33013a89`, senza un piano approvato tracciato.
- **P07 STOP-1:** l'analisi è stata scritta "in attesa di approvazione", revertata 8 ore dopo, e il lavoro è ripartito con uno scope diverso. Le 8 decisioni dell'analisi non hanno risposta in git.
- **P06 STOP-1:** destinazione del QR, 4 report e campi storicizzati scelti in autonomia.
- **P05 STOP-1:** nessun piano MVP tracciato.
- **P02 STOP-2:** i guardrail critico/KEV sono spegnibili da UI.
- **P01 STOP-1:** nessuna richiesta del file fattura tracciata.

**Versione:** bump assente per P01, P02, P04, P05 e P07. Il bump a 1.6.2 è arrivato con P06, che ha inserito `## 1.6.2` subito sotto `[Unreleased]` nel CHANGELOG, inglobando le voci di altre sessioni.

## 5. Promesse non mantenute

| Dove | Dichiarazione | Esito della verifica |
| --- | --- | --- |
| `6416affe` (P07) | "reset protetto, permesso copia lato server" | Reset con backup incompleto; il permesso copia si aggira senza parametro |
| `docs/moduli/timbri.md:22` (P07) | "Permessi copia/download ACL v2" | Sono permessi legacy (`timbri/acl_bootstrap.py`) |
| Branch `feature/timbri-rifacimento` / merge `359480a6` (P07) | rifacimento | Il commit `fed75016` stesso dice "Solo presentazione: view, permessi, modelli e dati invariati": del rifacimento non c'è nulla |
| `37d6a78c` (P04) | "chiusura A8 referti … upload validati" | Download chiuso; il "sostituisci" di `referto_gestione` accetta ancora DOC/XLS/WEBP |
| `aff8f990` (P06) | "storico rete/assegnazioni" | MAC e dati tecnici assenti |
| Merge `1f2c73c2` (P05) | "e-learning professionale (prompt 05 fasi 1+2)" | Mancano: assegnazione per gruppi, IP/dispositivo nel registro, rettifiche, nh3, download dell'attestato da parte del discente |
| `5e9c9518` (P02) | "registro regole di rientro con simulazione" | La simulazione esiste, ma non riusa `rule_simulation.py` come richiesto |
| Report P01 (dalla mappa del mandato) | "dashboard e wizard in main" | Vero. Ma A e B, i due bug che aprivano il prompt, sono rimasti senza riproduzione e senza correzione |

## 6. Cosa resta da fare (per priorità)

**P07 Timbri**
1. **S:** backup completo prima del reset (tutti i registri, immagini, stati) oppure eliminazione del reset.
2. **S:** chiudere il bypass `serve_timbri_image`.
3. **S:** proteggere `cleanup_orphan_operatori` e `operatore_delete`.
4. **L:** il rifacimento vero: modello `Timbro`/`AssegnazioneTimbro`, state machine, univocità DB, "chi aveva X il giorno Y", watermark, specimen, ricevute, import con conflitti. Prima vanno date le **risposte alle 8 decisioni** dell'analisi `bbeb212a`.

**P02 SOC**
1. **S:** escludere dall'impronta appresa gli eventi di rientro ("completed", 0 esposti), con test.
2. **S:** decidere se i guardrail critico/KEV possono essere spenti.
3. **S:** binding ACL per le route nuove.
4. **M:** sezione impatto sul finding, test di `suggest_cpe`/notifica/ordinamento, riuso di `rule_simulation`.
5. **S:** merge (conflitto solo nel CHANGELOG) e bump.

**P01 Contatori**
1. **M:** riprodurre e correggere il bug fattura (serve il file da Brizio): test dei formati, duplicati numero+fornitore+data, limite pagine, associazione manuale.
2. **M:** analisi reparti: macchine disattivate, buchi dichiarati, storico reparto, test grafico = xlsx.
3. **S:** limitare a chi inviare la community nel test di connessione.
4. **S:** N+1 di `riconcilia` sulla Centrale.
5. **S:** catalogo errori in "Ultimi errori", URL nella doc.

**P04 Mansioni**
1. **S:** timeline neutra senza permesso visite; monitoring senza righe visite.
2. **S:** gate in-view sul pannello.
3. **M:** "requisiti senza adempimento" e "visite scadute" nel controllo notturno; voce visita generica legata al tipo.
4. **S:** ricalcolo al cambio protocollo; "sostituisci" referto con `valida_referto`; 5 `except: pass`.

**P05 E-learning**
1. **S:** download dell'attestato per il discente.
2. **M:** registro con IP/dispositivo configurabile e rettifiche tracciate, protezione dagli UPDATE.
3. **M:** assegnazione per gruppi.
4. **S:** nh3 o decisione motivata; 401 JSON sul battito; "in scadenza" e tempo medio reale nel cruscotto; test del PDF.

**P06 Asset**
1. **S:** KPI della scheda con "dato non disponibile" anche nel TCO.
2. **M:** storico del MAC (manca il campo) e dei dati tecnici, scrittura dai job.
3. **S:** controllo MIME sugli import, log in `report_catalog`, `assertNumQueries` sulla pagina, test di diniego OdL.
4. **S:** riordinare il CHANGELOG (1.6.2 / Unreleased).

**P03 Anagrafica elenco/admin, L, da avviare**
- Registro colonne con permessi, viste e preset, export.
- Wizard di creazione con LDAP in sola lettura e regole A3/M2.
- Hub admin con import nelle pagine delle entità.

Il rischio del collegamento per prefisso email (§4.7) è **S** e va fatto subito, anche separatamente.

**P08 Audit interni, L, da avviare** (si parte dalla gap analysis):
- Programma triennale e indipendenza con override.
- Classificazione NC maggiore/minore.
- Integrazione `anomalie`.
- Solleciti e chiusura condizionata.
- Hash del rapporto ed export xlsx.
- Ruolo auditato.
- Cruscotto.

**Trasversale, S:** bump di versione e scheda modulo per ogni promozione; rigenerare `SetupWizard.exe` (P06 ha toccato `setup_wizard.py`).

## 7. Cosa deve verificare Brizio a mano

| # | Elemento | Passo | Risultato atteso |
| --- | --- | --- | --- |
| 1 | P05-A4 player da smartphone | Aprire un corso da `/anagrafica/formazione/corsi-online/` a 375 px, tema chiaro e scuro | Slide, video e pulsanti leggibili e senza scroll orizzontale |
| 2 | P01-STOP-1 fattura | Fornire la fattura anonimizzata che dà errore e il messaggio esatto | Base per riprodurre il bug A |
| 3 | P01-B1 andamento reparti | Descrivere cosa non va (dati, lentezza, grafico vuoto) | Base per il bug B |
| 4 | ACL strict in produzione | Dopo `migrate`, eseguire `acl_coverage_report --only-unbound` sul DB di produzione; aprire `/soc/soppressioni/`, `/soc/vulnerabilita/` e il pannello sicurezza di un dipendente con un utente non superuser | Nessuna route nuova scoperta; pagine accessibili solo con il permesso giusto |
| 5 | P07 decisioni | Rispondere alle 8 decisioni dell'analisi `bbeb212a` (riassegnazione e quarantena, ruoli, MT CN 06, CNOT116, diciture, unificazione con gestione_specifiche, codici vuoti, priorità) | Sblocca il rifacimento |
| 6 | P06 QR | Confermare: landing interna di default e link pubblico opt-in per asset; token esistenti della 0069 lasciati attivi | Decisione esplicita |
| 7 | P06 report | Confermare che i 4 report del catalogo sono quelli utili | |
| 8 | P02 guardrail | Decidere se `escludi_critici`/`escludi_kev` possono restare spegnibili da UI | |
| 9 | P04 RSPP / medico | Validare la regola "non idoneo salvo deroga motivata, max 30 giorni" e i testi neutri | |
| 10 | P05 RSPP | Confermare le regole FAD (tempo minimo, slide, quiz) per i corsi sicurezza | |
| 11 | P06 "Leggi ora" | Su una MFC reale, premere "Leggi adesso" con django-q attivo | Stato "in coda" → esito, nessun blocco della pagina |
| 12 | Pacchetto | Prima del deploy, ricostruire `SetupWizard.exe` | |

## 8. Controllo dei controllori

L'auditor ha ricontrollato di persona:

| Prompt | Ricontrollato | Esito |
| --- | --- | --- |
| P07 | backup pre-reset, bypass copia | entrambi confermati |
| P03 | assenza totale del lavoro (pickaxe `VistaElenco`), collegamento per prefisso | confermati |
| P08 | assenza di commit dopo il 09/10 | confermata |
| P01 | `novicromprinter`, B5/B6 | confermati |
| P04 | gate del pannello | confermato, ma severità ridotta: con lo strict la route senza binding è negata |
| P05 | SEC2 (le domande servite non contengono `corretta`), attestato che richiede il permesso HR | confermati |
| P06 | SEC1 (unici punti di generazione del token) | confermato |
| P02 | impronta senza stato + ordine soppressione/valutazione | confermato |

Nessun FATTO ricontrollato è risultato falso, quindi non è servito un riesame completo dei FATTO di nessun subagent.

Deviazioni dei subagent dalle regole:
- quello di P04 ha scritto e cancellato subito un file temporaneo nello scratchpad;
- quello di P02 ha interrotto un `git ls-tree` andato oltre il timeout.

Nessun file del repo è stato modificato.
