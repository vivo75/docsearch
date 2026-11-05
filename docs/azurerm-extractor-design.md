# Estrattore deterministico per il provider Terraform azurerm — valutazione e progetto

Data: 2026-11-05. Stato: prototipo in corso (vedi "Prototipo" in fondo).

## Richiesta
Un tool dell'MCP che, dato un oggetto del provider `hashicorp/terraform-provider-azurerm` (es. `azurerm_mysql_flexible_server`),
legga il codice del provider e restituisca:

1. un JSON con tutti i tipi e i valori possibili delle variabili (argomenti) dell'oggetto;
2. un diagramma di flusso del codice;
3. le API di Azure che il codice richiama.

## Risposta: è fattibile, come estrattore deterministico
Si analizza il codice Go senza usare un modello a ogni chiamata. Ho guardato un file reale
(`internal/services/mysql/mysql_flexible_server_resource.go`, 1.136 righe): è regolare. Il provider ha 693 risorse
(`*_resource.go`) e 231 data source (`*_data_source.go`) in circa 5.500 file Go non di test.

### Perché è fattibile
- **Schema e valori ammessi sono dichiarativi.** Ogni argomento è una struttura Go con `Required`/`Optional`/`Computed`,
  `ForceNew`, `Default`, `ConflictsWith`, `ValidateFunc`. Nel file di esempio: `validation.StringInSlice([]string{...})`,
  `validation.IntBetween(1, 35)`, `Default: 7`. Un parser li legge in modo esatto.
- **Le chiamate alle API sono risalibili.** Create/Read/Update/Delete usano un client dell'SDK (`client.CreateCallbackThenPoll`,
  `client.Get`, …). Dal client si arriva al file dell'SDK (`hashicorp/go-azure-sdk`), che dichiara metodo HTTP, percorso REST e
  versione API (es. `2023-12-30`).
- **Gli strumenti esistono.** `tree-sitter` è già installato; Go non c'è. Il modulo Python `tree-sitter` + `tree-sitter-go` va aggiunto al venv.

### Cosa darebbe il tool
Un JSON per risorsa con:
- argomenti, tipi, obbligatorietà, default, vincoli reciproci (ConflictsWith, ExactlyOneOf, RequiredWith, AtLeastOneOf), blocchi annidati;
- enum quando sono letterali nel codice o risolvibili nell'SDK;
- elenco ordinato delle chiamate API (operazione, metodo e percorso HTTP, versione);
- un diagramma Mermaid delle funzioni Create/Read/Update/Delete, con rami e funzioni di supporto.

### Limiti
- **Enum esterni**: `servers.PossibleValuesForCreateMode()` sta in `hashicorp/go-azure-sdk`. Si risolve scaricando solo il
  `constants.go` del pacchetto alla versione fissata in `go.mod` (raw GitHub), oppure con le specifiche REST già indicizzate.
- **Validatori personalizzati** (`validate.FlexibleServerName`): si riportano per nome ed estratto del codice; non sempre si traducono in una regola semplice.
- **"Tutti i valori possibili" = quelli che il provider accetta**, non necessariamente quelli di Azure. Valori calcolati a runtime non si enumerano.
- **Il flusso è meno preciso dello schema**: un diagramma delle chiamate in ordine con rami `if`/cicli è realistico; un grafo di controllo completo no.
- **Versione**: il codice su `main` può differire dal provider fissato dall'utente; servirebbe un parametro `ref`/tag.

## Costo
- Esecuzione: nessun costo (solo parsing, millisecondi per risorsa; nessun LLM).
- Sviluppo: prototipo su 10 risorse ≈ mezza giornata; copertura larga ≈ 2–3 sessioni (le risorse con funzioni di schema condivise o generate sono il lavoro lungo).
- Spazio: clone sparse di `internal/services` (poche centinaia di MB) + file dell'SDK scaricati a richiesta.

## Validazione senza giudizi umani
La documentazione già indicizzata dichiara gli stessi valori ("possible values are …"). Si confrontano automaticamente enum e
obbligatorietà estratti dal codice con quelli della pagina `azurerm-docs/resources/<nome>.md`.

## Alternativa più economica
Un tool che restituisce il sorgente Go di una risorsa (sola lettura) e lascia l'analisi all'agente chiamante: sviluppo quasi nullo,
ma ~14.000 token per risposta e risultati meno ripetibili. Può essere un primo passo.

## Raccomandazione
Estrattore deterministico, con prototipo su 10 risorse e validazione contro la documentazione prima di esporlo come tool MCP.

## Prototipo
- Estrattore: `src/docsearch/azurerm_extract.py` (tree-sitter-go, nessun LLM). Entry point: `extract(name, kind="resource")`.
- Validazione: `eval/azurerm_validate.py` confronta ciò che l'estrattore legge dal codice con la pagina della stessa risorsa in `azurerm-docs`. Risultati: `eval/results/azurerm-validate.json`.
- Sorgenti: `terraform-provider-azurerm` (sparse, `internal/services/*`), enum e operazioni REST da `go-azure-sdk` alla versione in `go.mod`, scaricati una volta in `data/azurerm-cache/`.

### Esito del prototipo (2026-11-05, 11 risorse)
| Risorsa | Argomenti nel codice | Nella doc | Abbinati | Required/optional concordi | Enum doc / estratti / concordi | Chiamate API |
|---|---|---|---|---|---|---|
| azurerm_mysql_flexible_server | 45 | 40 | 40 | 39 | 5 / 3 / 3 | 5 |
| azurerm_kubernetes_cluster | 182 | 267 | 163 | 162 | 19 / 16 / 15 | 13 |
| azurerm_storage_account | 166 | 90 | 90 | 89 | 16 / 11 / 11 | 7 |
| azurerm_key_vault | 26 | 25 | 25 | 25 | 4 / 3 / 3 | 6 |
| azurerm_linux_virtual_machine | 91 | 82 | 82 | 81 | 12 / 12 / 12 | 11 |
| azurerm_virtual_network | 33 | 31 | 31 | 31 | 7 / 3 / 3 | 3 |
| azurerm_postgresql_flexible_server | 50 | 48 | 48 | 48 | 5 / 5 / 5 | 5 |
| azurerm_mssql_server | 27 | 23 | 23 | 23 | 2 / 2 / 2 | 10 |
| azurerm_cosmosdb_account | 78 | 61 | 61 | 60 | 8 / 7 / 7 | 7 |
| azurerm_service_plan | 12 | 12 | 12 | 12 | 2 / 0 / 0 | 3 |
| azurerm_linux_web_app | 121 | 194 | 115 | 113 | 16 / 15 / 13 | 29 |

Totale: 690 argomenti abbinati su 873 documentati; required/optional concordi su 683 di 690; enum concordi su 74 di 77 estratti (96 enum documentati in totale).

### Limiti noti
- **Enum estratti ma non concordi:** in parte sono difetti del validatore, che legge male la doc (per esempio `tls_aes_256_gcm_sha384"` con la virgoletta finale, o valori di altri campi finiti nella stessa lista). Vanno sistemati nel parser della doc prima di fidarsi del confronto.
- **Argomenti documentati ma non trovati nel codice:** soprattutto blocchi annidati di schemi condivisi (ACI connector, sicurezza di rete del cluster, CORS dello storage, cronologia dei valori delle app web). Il codice li costruisce con helper che l'estrattore non segue fino in fondo.
- **`azurerm_container_app_environment`:** non trovata. Il suo codice è in una cartella che il registro non segue con lo stesso schema.
- **`azurerm_service_plan`:** la risorsa è tipizzata (framework nuovo), quindi lo schema e i metodi CRUD seguono un altro percorso; gli enum non vengono estratti.
- **Chiamate API:** risolte 73 chiamate in 11 risorse; le operazioni sono ricavate dalle funzioni `*ThenPoll` e dall'SDK alla versione fissata.

### Prossimi passi
1. Sistemare il parser della doc (virgolette, liste miste) e rifare la validazione.
2. Seguire gli helper di schema condivisi per i blocchi annidati mancanti.
3. Aggiungere il supporto ai data source e al percorso tipizzato per gli enum.
4. Solo dopo, esporre un tool MCP che restituisce il JSON per risorsa.
