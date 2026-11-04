# Diario del lab

## 2026-10-31 — Preflight (§4.0)

- Profilo `mylabs`, regione `eu-west-1`.
- `aws --version` → `aws-cli/2.22.30`: `aws lambda help` non elenca comandi Web Functions né NetworkConnector. Serve una CLI più recente (brew ha la 2.38.5).
- `aws lambda get-account-settings` → `ConcurrentExecutions = 10`, `UnreservedConcurrentExecutions = 10`.
  Service Quotas `L-B99A9384` (Concurrent executions): valore 10, adjustable, nessuna richiesta di aumento in corso.
  Con 10 il piano di carico (fino a 500 VU, reserved concurrency 500 per funzione) non è eseguibile: STOP come da piano.
- Richiesta di aumento `L-B99A9384` a 1.100 in eu-west-1: stato `CASE_OPENED`, case 179344024600441.
- CLI aggiornata a `aws-cli/2.39.3`. Le Web Functions non stanno sotto `aws lambda`: hanno un namespace a parte, `aws lambda-web`
  (create-web-function, create-web-function-revision, create-web-function-endpoint, deploy, get-web-account-settings, ...).
  Il NetworkConnector sta in un altro namespace ancora, `aws lambda-core` (create-network-connector, list-network-connector-versions, ...).
- `aws lambda-web get-web-account-settings`: `maxTotalArmVCpus` 200, `maxTotalRateLimit` 10000, `maxRevisionsPerFunction` 50,
  `maxEndpointsPerFunction` 10, `functionCount` 0. Le Web Functions hanno quote proprie, separate dalla concorrenza delle Event Functions.
- Le due API hanno convenzioni diverse: `lambda-web list-web-functions` risponde in camelCase (`functions[].functionName`),
  `lambda-core list-network-connectors` in PascalCase (`NetworkConnectors[].Name`, `LatestVersionArn`).
- `aws-cdk-lib` 2.275.0 (Python) ha già gli L1 `CfnWebFunction`, `CfnWebFunctionRevision`, `CfnWebFunctionEndpoint`, `CfnNetworkConnector`.
  `ServiceConfig` espone già `egress_network_connector_arn`: l'override del piano (§2, punto 2) qui non serve.
  `ServiceConfig` ha `max_concurrency_per_environment` e `timeout_seconds`; nessun campo memoria/vCPU nella revisione.
  `ScalingConfig.max_environments` e `ThrottleConfig.rate_limit` stanno sull'endpoint, non sulla revisione.
- Node locale è 23.6.0 (EOL): la CDK CLI avvisa. Le funzioni girano su Node 24 in Lambda; in locale Node serve solo per `npm ci` e la CDK CLI.

## 2026-10-31 — Documentazione Web Functions e prezzi eu-west-1 (§4.0 punti 3-4)


Raccolte il 2026-10-31. Solo letture, nessuna risorsa creata.
Base URL docs: `https://docs.aws.amazon.com/lambda/latest/dg/` (abbreviato **DG/**). Le pagine sono state scaricate anche in versione `.md` (stesso slug).
Fonti autorevoli locali: `aws cloudformation describe-type` (eu-west-1, file `../notes/schema_*.json` (fuori dal repo)), `aws lambda-web ... help` / `aws lambda-core ... help` (CLI 2.39.3, file help della CLI).

Legenda: **[NON TROVATO]** = non documentato; **[AMBIGUO]** = fonti discordanti o poco chiare; **[DISCORDANZA]** = docs/CLI/schema CFN non coincidono.

---

## 1. Modello di risorse

- Tre risorse: Web Function (contenitore con nome), Revision (snapshot immutabile di codice + config), Endpoint (dominio HTTPS + auth + routing verso 1 o 2 revision). Fonte: DG/web-functions-how-it-works.html, blog https://aws.amazon.com/blogs/compute/exploring-aws-lambda-web-functions-for-building-web-applications/
- Al lancio: solo Node.js 24 su Arm64, **2 vCPU e 2 GB fissi per execution environment**, non configurabili. Fonte: blog compute (sopra), DG/web-functions-configuration-architecture.html, quote in DG/gettingstarted-limits.html#web-functions-quotas
- API in camelCase (`buildConfig`, `codeConfig`, `serviceConfig`); il PascalCase dà `Unknown parameter: BuildConfig`. In CloudFormation invece le proprietà sono PascalCase. Fonte: DG/web-functions-troubleshooting.html
- Comandi `aws lambda-web`: create-web-function, create-web-function-revision, create-web-function-endpoint, update-web-function-endpoint, get-/list-/delete-*, put-/get-/delete-resource-policy, get-web-account-settings, deploy (comando composito di alto livello), wait. `aws lambda-core`: create-/get-/update-/delete-network-connector, list-network-connectors, list-network-connector-versions. Fonte: `aws lambda-web help`, `aws lambda-core help`
- `create-web-function` accetta `--revision-config` e `--endpoint-config` (crea funzione, prima revision e primo endpoint in una chiamata). Fonte: CLI help, DG/web-functions-code-s3.html

## 2. Proprietà della Revision

Fonte primaria: `aws lambda-web create-web-function-revision help`, DG/web-functions-revisions.html (tabella "Revision properties").

- `functionName` (obbligatorio), `description` (0-256), `kmsKeyArn` (opzionale, cifra codice ed env var).
- `buildConfig` (obbligatorio):
  - `codeConfig.s3Object` = `{ bucket, key, versionId? }`. **Unico modo di fornire il codice** è uno .zip su S3. Fonte: DG/web-functions-code-s3.html
  - `runtimeConfig.runtime`: unico valore supportato `nodejs24.x`. Fonte: DG/web-functions-runtimes.html
- `serviceConfig` (obbligatorio):
  - `executionRoleArn` (obbligatorio)
  - `timeoutSeconds`: 3-900, default 30 (timeout per singola richiesta HTTP; oltre si ottiene HTTP 504 `Runtime.RequestTimeout`). Fonte: DG/web-functions-revisions-timeout.html
  - `maxConcurrencyPerEnvironment`: 1-128, default 64
  - `environmentVariables`: mappa; dimensione max 32 KB totali (quote); chiavi `[a-zA-Z][a-zA-Z0-9_]*`
  - `egressNetworkConnectorArn`: ARN **versionato** del network connector (`...:network-connector:<nome-o-id>:<versione>`)
  - `telemetryConfig.loggingConfig` = `{ logGroup (default /aws/lambda/web/<function>), applicationLogLevel (default INFO), systemLogLevel (default INFO) }`
- **Nessuna proprietà di memoria / vCPU / architettura / handler** né nello schema API né in CFN (coerente con le docs: 2 vCPU, 2 GB fissi, solo arm64).
- Entrypoint: per default il runtime carica `index.js` nella root dello zip; per cambiarlo si imposta l'env var `AWS_LAMBDA_NODEJS_ENTRYPOINT` (percorso relativo alla root del pacchetto, es. `dist/index.js`). Il runtime **non** legge `main` da `package.json`. Fonte: DG/web-functions-revisions-env-vars.html, DG/web-functions-configuration-deployment-package.html
  - `aws lambda-web deploy --entry-point` è solo una comodità della CLI: se il file non è `index.js` aggiunge un wrapper `index.js` che lo importa. Fonte: `aws lambda-web deploy help`
- Tutte le proprietà sono immutabili: ogni modifica = nuova revision, che **non** eredita nulla dalla precedente (le impostazioni omesse tornano ai default). Fonte: DG/web-functions-revisions.html
- Stati della revision: `Pending`, `Active`, `Failed`. `Failed` è **permanente**. Fonte: DG/web-functions-revisions.html, DG/web-functions-code-s3.html
- Massimo 50 revision per funzione (target di pulizia automatica: Lambda cancella le più vecchie non instradate). Fonte: DG/gettingstarted-limits.html#web-functions-quotas

### Requisiti per il bucket S3 del codice (DG/web-functions-code-s3.html)
- Il bucket **deve avere il versioning abilitato**. `versionId` è opzionale: se manca, Lambda fissa la revision sull'ultima versione esistente al momento della creazione.
- Pacchetto max 512 MB (decompresso). Deve includere `node_modules`; le dipendenze native vanno compilate per Linux arm64.
- **Bucket policy** che concede a `lambda.amazonaws.com` `s3:GetObject` + `s3:GetObjectVersion`, con condizione `ArnLike aws:SourceArn = arn:aws:lambda:<region>:<account>:web-function/<fn>/revision/*`. Con SSE-KMS serve anche `kms:Decrypt` per `lambda.amazonaws.com` nella key policy. Lambda verifica l'accesso alla creazione della revision e rifiuta la richiesta se manca.
- Anche il chiamante deve avere `s3:GetObject` e `s3:GetObjectVersion` sull'oggetto.
- Il bucket può stare in un altro account/Region (stessa partition, non in una Region opt-in).
- Lambda legge il codice **direttamente dal tuo bucket**: se cancelli la versione dell'oggetto o togli il permesso, la revision diventa `Failed` (in modo permanente) e le richieste instradate lì ricevono HTTP 409 `Platform.RevisionNotActive`.
- Lambda **non verifica** che il server sia in ascolto quando crea la revision o aggiorna l'endpoint: revision ed endpoint possono risultare `Active` anche con un'app rotta. Serve una richiesta di test dopo ogni deploy.
- `aws lambda-web deploy` senza `--bucket-name` usa un bucket gestito `awscli-lambdaweb-<account-id>-<region>-an` e crea il ruolo `awscli-lambdaweb-<name>` se non lo passi. Fonte: `aws lambda-web deploy help`

## 3. Proprietà dell'Endpoint

Fonte primaria: `aws lambda-web create-web-function-endpoint help`, DG/web-functions-endpoints.html, DG/web-functions-scaling.html.

- `functionName`, `endpointName` (obbligatori), `description`.
- `endpointType` (obbligatorio, immutabile): `HomeRegion` | `MultiRegion` | `PerRegion`.
- `authType` (obbligatorio, **modificabile** con update): **`ApplicationManaged`** (nessuna auth da Lambda, endpoint pubblico) | **`IamAuth`** (SigV4, o SigV4a per MultiRegion; nome servizio per la firma: `lambda`; azione IAM `lambda:InvokeWebFunctionEndpoint`). Fonte: DG/web-functions-endpoint-access-control.html
- `autoDeploymentMode`: `LatestRevision` | `Disabled`. **Default API = `Disabled`**; console e `deploy` usano `LatestRevision` per i nuovi endpoint HomeRegion. Con `Disabled` servono `revisionWeights` che sommano a 100. Fonte: DG/web-functions-endpoints.html
- `revisionWeights`: 1-2 voci `{ revisionId, weight 1-100 }`.
- `regions`: solo per MultiRegion/PerRegion, immutabile.
- **`scalingConfig.maxEnvironments`**: opzionale, nessun default, 2-10.000, applicato per Region. Senza valore il limite è solo la quota vCPU dell'account. Per azzerarlo: `--scaling-config '{}'`.
- **`throttleConfig.rateLimit`**: opzionale, nessun default, in richieste al secondo per Region; valori ammessi: 0, 100-1.000 a passi di 100, 2.000-10.000 a passi di 1.000. `0` blocca tutto (HTTP 503 `Platform.EndpointDisabled`). Per azzerarlo: `--throttle-config '{}'`.
- `maxEnvironments` e `rateLimit` si cambiano con `update-web-function-endpoint` senza nuova revision; `maxConcurrencyPerEnvironment` invece richiede una nuova revision.
- Dominio: `<id>.<xyz>.lambda-web.<region>.on.aws` (esempio `bcdfghjklmnpqrst.b7t.lambda-web.us-east-1.on.aws`); solo HTTPS sulla 443, HTTP/1.1. Nessun dominio custom, nessuna associazione WAF diretta, **nessun PrivateLink**: l'endpoint è sempre raggiungibile da internet. Fonte: DG/web-functions-http.html, DG/web-functions-networking.html
- Fino a 10 endpoint per funzione. Fonte: quote.
- Il gating dell'invocazione con IamAuth dà HTTP 403 per richieste non firmate o non autorizzate. Fonte: DG/web-functions-troubleshooting.html

## 4. Come deve mettersi in ascolto l'app; identificare l'environment

- Lambda imposta **`AWS_LAMBDA_HTTP_ENDPOINT`** in formato **`host:port`**. L'app deve fare il bind esattamente su quell'host e quella porta (né `localhost` né una porta fissa). La variabile è riservata e non si può impostare. Esempio dalle docs: `const [host, port] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || 'localhost:3000').split(':'); app.listen(port, host);`. Fonte: DG/web-functions-runtimes.html, DG/web-functions-revisions-env-vars.html
- Il server deve essere in ascolto **entro 10 secondi** (init timeout, non modificabile), altrimenti `Application.TimeoutListenError`. Un bind solo su loopback (127.0.0.1/localhost) causa questo errore o un HTTP 502. Fonte: DG/web-functions-env-lifecycle.html, DG/web-functions-troubleshooting.html
- Altre env var presenti: `AWS_LAMBDA_FUNCTION_MEMORY_SIZE`, `AWS_LAMBDA_METADATA_API`, `AWS_LAMBDA_METADATA_TOKEN`. Le docs avvertono che non tutte le env var delle Event Function sono presenti. Nomi riservati: credenziali AWS_*, `AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_LAMBDA_HTTP_ENDPOINT`, `AWS_LAMBDA_RUNTIME_API`, `AWS_LAMBDA_INITIALIZATION_TYPE`, `AWS_LAMBDA_FUNCTION_MEMORY_SIZE`, `AWS_LAMBDA_METADATA_*`. Fonte: DG/web-functions-revisions-env-vars.html
- Identificare l'environment:
  - header di risposta **`lambda-web-logstream`** = log stream dell'environment che ha servito la richiesta (un log stream per environment). Fonte: DG/web-functions-http.html, DG/web-functions-logging.html
  - header **`lambda-web-request-id`** (sia nella richiesta inoltrata all'app sia nella risposta), `lambda-web-endpoint-name` (nella richiesta). Fonte: DG/web-functions-http.html
  - i log di sistema (`platform.initStart`, `platform.invokeSummary`, `platform.invokeReport`, `platform.spinDownStart`) riportano `instanceId` (UUID dell'environment) e `revisionId`. Fonte: DG/web-functions-logging-system-log-schema.html
  - l'endpoint metadata (`http://$AWS_LAMBDA_METADATA_API/2026-01-15/metadata/execution-environment`, header `Authorization: Bearer $AWS_LAMBDA_METADATA_TOKEN`) restituisce `AvailabilityZoneID`. Fonte: DG/web-functions-configuration-metadata-endpoint.html
  - **[NON TROVATO]** una env var documentata con l'ID dell'environment o il nome del log stream leggibile dal codice. In pratica l'ID è visibile all'esterno solo tramite l'header `lambda-web-logstream` (oppure si genera un UUID all'avvio del processo).
- Heap V8 di default 1.024 MB su 2 GB di RAM; si alza con `NODE_OPTIONS=--max-old-space-size=...`. `/tmp` da 512 MB condiviso fra le richieste concorrenti. Massimo 1.024 file descriptor e 1.024 processi/thread. Fonte: DG/web-functions-runtimes.html, quote
- Shutdown: Lambda smette di instradare, lascia finire le richieste in corso (best effort), invia `SIGTERM` e concede **1 secondo** prima di terminare. Fonte: DG/web-functions-env-lifecycle.html
- HTTP: metodi GET/HEAD/POST/PUT/PATCH/OPTIONS/DELETE; HTTP/1.0 riceve 505; header fino a 128 KiB (oltre: 431); niente WebSocket; percorso half-duplex (l'app deve leggere tutto il body prima di rispondere); niente CORS automatico. Fonte: DG/web-functions-http.html, DG/web-functions-networking.html

## 5. Scaling, concorrenza, throttling

Fonte: DG/web-functions-scaling.html salvo diversa indicazione.

- Lo scaling avviene su due assi: numero di environment (fino a `maxEnvironments` o alla quota vCPU) e richieste concorrenti per environment. La concorrenza per environment è un **limite dinamico gestito da Lambda**, il cui tetto è `maxConcurrencyPerEnvironment` (default 64, max 128).
- Il limite dinamico **parte basso** per una funzione nuova e cresce in base all'uso di risorse; Lambda lo **ricorda** anche dopo lo scale-to-zero. Conseguenza per i lab: il primo load test su una funzione nuova usa più environment dei successivi. Le docs consigliano di ripetere il test e usare i run successivi.
- Scale-to-zero senza traffico; **nessun minimo né environment riservati** (niente equivalente della provisioned concurrency). Lambda mantiene una riserva di capacità (headroom) avviando environment in anticipo.
- Throttling: **HTTP 429 Too Many Requests**, con header `lambda-web-error-type`:
  - `Platform.EndpointRequestThrottle` (superato `rateLimit` o la quota per endpoint)
  - `Platform.AccountRequestThrottle` (superata la quota RPS dell'account)
  - `Platform.EndpointMaxEnvThrottle` (raggiunto `maxEnvironments` con tutti gli environment saturi)
  - `Platform.AccountActiveVCPUArm64Throttle` (raggiunta la quota vCPU)
  - `Platform.EndpointConcurrentInitThrottle` (troppi environment in init contemporaneamente; **non incrementa nessuna metrica di throttle**)
  - Le richieste in throttling non vengono accodate. Se però un environment è in inizializzazione, le richieste aspettano in coda invece di ricevere subito 429.
- `rateLimit = 0` restituisce **HTTP 503** `Platform.EndpointDisabled`. Un 503 senza header può indicare load shedding: va ritentato con backoff. Fonte: DG/web-functions-scaling.html, DG/web-functions-troubleshooting.html
- Altri codici: 409 (`Platform.RevisionNotActive` / `EndpointNotActive`), 502 (init fallita o risposta non valida), 503 (crash dell'app: `Runtime.Unreachable` ecc.), 504 (`Runtime.RequestTimeout`). Fonte: DG/web-functions-troubleshooting.html
- `maxEnvironments` può essere superato brevemente durante eventi operativi (cambio dei pesi delle revision, ciclo della flotta). Le richieste in throttling compaiono in `HTTPResponseStatusClass4XX`.
- Quote da docs (per Region): 10.000 RPS per endpoint, 100.000 RPS per account, **2.000 vCPU Arm64** per account (cioè 1.000 environment). Fonte: DG/web-functions-scaling.html, DG/gettingstarted-limits.html#web-functions-quotas
- **Quote REALI dell'account `mylabs` in eu-west-1** (`aws lambda-web get-web-account-settings`): `maxTotalArmVCpus: 200` (= **100 environment massimi**), `maxTotalRateLimit: 10000` RPS, `maxRevisionsPerFunction: 50`, `maxEndpointsPerFunction: 10`, `functionCount: 0`. **Più basse dei default documentati** (2.000 vCPU / 100.000 RPS). Da tenere presente per il dimensionamento del load test.

## 6. Metriche CloudWatch

Fonte: DG/web-functions-monitoring-metrics.html

- Namespace **`AWS/Lambda/Web`** (centralizzato nella home Region):
  - Metriche di richiesta, dimensioni **`FunctionName` + `EndpointName`**, unità Count, statistica Sum: `ExecutedRequests`, `HTTPResponseStatusClass4XX`, `HTTPResponseStatusClass5XX` (sparse: nessun punto quando il valore è 0).
  - Metriche di environment, dimensione **solo `FunctionName`** (niente EndpointName), emesse ogni minuto per ogni environment attivo: `EnvironmentActiveTime` (ms, Sum, include l'init), `EnvironmentCPUTime` (ms, Sum, include l'init), `EnvironmentMaxMemoryUsage` (MB, Maximum), `EnvironmentConcurrentRequests` (Count, Maximum), `ResponseBytes` (Bytes, Sum). Le docs avvertono di non usare `SampleCount` per contare gli environment.
- Namespace **`AWS/Lambda/Web/Usage`** (per Region, non centralizzato), dimensioni **`FunctionName`, `EndpointName`, `ExecutionRegion`**: `ExecutedRequests`, `EndpointActiveEnvironments` (Maximum: è il conteggio degli environment da usare), `AccountRequestThrottles`, `EndpointRequestThrottles`, `AccountActiveVCPUArm64Throttles`, `EndpointActiveEnvironmentThrottles`.
- **Non esiste una metrica di latenza/durata** e non esiste una dimensione per revision. La latenza va misurata lato client, con EMF o dai log. Con `systemLogLevel=DEBUG` si ottiene `platform.requestComplete` per ogni richiesta (con `durationMs`, `result`, `requestId`, `endpointName`). `platform.invokeSummary` (circa ogni 60 s) e `platform.initReport` riportano `cpuTimeMs` / `totalDurationMs` / `totalCpuTimeMs`. Fonte: DG/web-functions-logging.html, DG/web-functions-logging-system-log-schema.html
- Le metriche vendute da Lambda sono gratuite; i log seguono le tariffe CloudWatch Logs. Log group: `/aws/lambda/web/<fn>` (centralizzato) e `/aws/lambda/web/<fn>.local` (regionale). Il ruolo di esecuzione deve avere `logs:CreateLogGroup/CreateLogStream/PutLogEvents`. Fonte: DG/web-functions-monitoring.html
- Nota di naming: l'error type `Platform.EndpointMaxEnvThrottle` corrisponde alla metrica `EndpointActiveEnvironmentThrottles` (i nomi non coincidono).

## 7. NetworkConnector (accesso VPC)

Fonte: DG/web-functions-networking.html, `aws lambda-core create-network-connector help`, schema CFN.

- Si crea con `aws lambda-core create-network-connector --name ... --configuration '{"VpcEgressConfiguration":{...}}' --operator-role <arn>` (configuration è una tagged union, oggi solo `VpcEgressConfiguration`).
- `VpcEgressConfiguration`: `SubnetIds` (1-16, stessa VPC; le docs chiedono **almeno 2 subnet in AZ diverse**), `SecurityGroupIds` (0-16), `NetworkProtocol` (`IPv4` | `DualStack`), `AssociatedComputeResourceTypes` (esattamente 1 valore: `WebFunction` oppure `MicroVm`, immutabile). Qui i campi sono PascalCase anche nella CLI.
- Ruolo operatore: trust per `lambda.amazonaws.com` con `sts:AssumeRole`. La policy di esempio nelle docs: `ec2:CreateNetworkInterface` su `network-interface/*`, `subnet/*`, `security-group/*` + `ec2:CreateTags` su `network-interface/*` con condizione `ec2:ManagedResourceOperator = network-connectors.lambda.amazonaws.com`. **[DISCORDANZA]** vedi sezione 9.
- Ruolo operatore e ruolo di esecuzione sono distinti; al ruolo di esecuzione non servono permessi ENI. Chi crea il connector o la revision ha bisogno di `lambda:PassNetworkConnector` sul connector e di `iam:PassRole` sul ruolo operatore e sul ruolo di esecuzione. Fonte: DG/web-functions-permissions.html
- Creazione asincrona: lo stato `PENDING` "**tipicamente fino a 10 minuti**" mentre vengono create le ENI, poi `ACTIVE`. Altri stati: `INACTIVE`, `FAILED`, `DELETING`, `DELETE_FAILED`. Dopo un update si controlla `LastUpdateStatus` (`InProgress`/`Successful`/`Failed`). Fonte: CLI help, DG/web-functions-networking.html
- Versioni: ogni update pubblica una **nuova versione immutabile**; la revision referenzia un ARN con versione (`arn:aws:lambda:<r>:<acct>:network-connector:<nome-o-id>:<N>`). ARN senza versione, nome o ID non sono accettati. Aggiornare il connector non tocca le revision esistenti: serve una nuova revision. `update-network-connector` sostituisce l'intera `VpcEgressConfiguration`. CFN espone `LatestVersion` e `LatestVersionArn` (GetAtt).
- Vincoli: 0 o 1 connector per revision; stesso account e Region; **solo endpoint `HomeRegion`**. Con un connector **il traffico verso internet passa dalla VPC**: per raggiungere destinazioni pubbliche IPv4 (es. Secrets Manager senza VPC endpoint) serve un NAT gateway, altrimenti servono VPC endpoint. IP sorgente non stabile: sul SG di Aurora si autorizza il SG del connector. DNS privato: servono DNS support/hostnames abilitati nella VPC. Fonte: DG/web-functions-networking.html
- Senza connector: egress pubblico IPv4 diretto, nessun accesso alla VPC.
- Cancellare un connector ancora referenziato da una revision attiva interrompe la connettività.

## 8. Limiti e gotcha utili per il lab

- Endpoint sempre pubblico; con `ApplicationManaged` chiunque conosca il dominio può chiamarlo (per un load test va bene, ma conviene mettere un token applicativo o usare `IamAuth` + SigV4). Fonte: DG/web-functions-best-practices.html
- Per un confronto equo: il primo run su una funzione nuova parte con il limite dinamico basso (sezione 5). Le metriche di environment non hanno EndpointName. Non c'è una metrica di latenza.
- Node è single-thread: il lavoro CPU-bound blocca tutte le richieste concorrenti dell'environment (anche se ci sono 2 vCPU, servono `worker_threads` per usarli). Fonte: DG/web-functions-runtimes.html
- Pool di connessioni al DB: le docs consigliano di riusare client e pool fra le richieste, di limitare il pool e di inizializzare in modo lazy. `EMFILE` indica connessioni non chiuse. Fonte: DG/web-functions-best-practices.html, DG/web-functions-troubleshooting.html
- I segreti vanno caricati a runtime (Secrets Manager), non messi nelle env var. Fonte: DG/web-functions-revisions-env-vars.html
- Le env var sono immutabili e la nuova revision non eredita nulla.
- Con `Disabled` (default API e unico comportamento possibile in CFN, vedi sotto) bisogna aggiornare `revisionWeights` a ogni nuova revision.

## 9. Schemi CloudFormation (eu-west-1) e discordanze

Tutti e 4 i tipi esistono in eu-west-1.

**AWS::Lambda::WebFunction**: required `FunctionName` (createOnly, max 64 caratteri se è un nome). Opzionale `Tags` [{Key,Value}]. Read-only: `FunctionArn` (primary id, `...:web-function/<name>`), `State` (Pending/Active/Failed/Deleting), `StateReason`, `CreatedAt`, `UpdatedAt`. **Nessun** equivalente di `revisionConfig`/`endpointConfig`: in CFN servono 3 risorse separate.

**AWS::Lambda::WebFunctionRevision**: required `FunctionName`, `BuildConfig`, `ServiceConfig`; tutto createOnly (ogni modifica sostituisce la risorsa, cioè crea una nuova revision).
- `BuildConfig` = { `CodeConfig` (req) = { `S3Object` (req) = { `Bucket` (req), `Key` (req), `VersionId` } }, `RuntimeConfig` (req) = { `Runtime` (req) } }
- `ServiceConfig` = { `ExecutionRoleArn` (req), `TimeoutSeconds` 3-900, `EgressNetworkConnectorArn` (pattern con `:<numero>` finale obbligatorio), `MaxConcurrencyPerEnvironment` 1-128, `EnvironmentVariables` (mappa, valori 1-4096 caratteri), `TelemetryConfig` = { `LoggingConfig` = { `LogGroup`, `ApplicationLogLevel`, `SystemLogLevel` } } }
- `Description`, `KmsKeyArn` opzionali. Read-only: `RevisionArn` (primary id), `RevisionId`, `FunctionArn`, `State`, `StateReason`, `CreatedAt`.

**AWS::Lambda::WebFunctionEndpoint**: required `FunctionName`, `EndpointName`, `EndpointType`, `AuthType`. createOnly: `FunctionName`, `EndpointName`, `EndpointType`, `Regions`. `AuthType` è modificabile.
- `AuthType` enum: `ApplicationManaged` | `IamAuth`. `EndpointType`: `HomeRegion` | `MultiRegion` | `PerRegion`.
- `RevisionWeights` [1-2] di { `RevisionId` (req), `Weight` 1-100 (req) }
- `ScalingConfig` = { `MaxEnvironments` (integer, minimum 2) }
- `ThrottleConfig` = { `RateLimit` (integer, minimum 0) }
- Read-only: `EndpointArn` (primary id), `DomainName`, `State`, `StateReason`, `UpdateStatus`, `UpdateStatusReason`, `RegionalEndpoints`, `FunctionArn`, `CreatedAt`, `UpdatedAt`.

**AWS::Lambda::NetworkConnector**: required solo `Configuration`; createOnly `Name`.
- `Configuration` = { `VpcEgressConfiguration` (req) = { `SubnetIds` (req, 1-16), `SecurityGroupIds` (req, 0-16), `NetworkProtocol` (req, IPv4|DualStack), `AssociatedComputeResourceTypes` (req, esattamente 1, MicroVm|WebFunction), `ElasticIpConfiguration` (schema vuoto `{}`) } }
- `OperatorRole` (opzionale), `Name`, `Tags`. Read-only: `Arn` (primary id), `State`, `LatestVersion`, `LatestVersionArn`.

**Discordanze e osservazioni:**
1. **[DISCORDANZA] `AutoDeploymentMode` non esiste nello schema CFN di WebFunctionEndpoint**, mentre esiste in API/CLI (default API `Disabled`). In CFN quindi l'endpoint gira presumibilmente in modalità `Disabled` e bisogna passare `RevisionWeights` con `!GetAtt Revision.RevisionId` e peso 100 **[AMBIGUO: comportamento dedotto, non documentato]**. Le docs dicono che con Disabled i pesi sono obbligatori; lo schema CFN invece non mette `RevisionWeights` fra i campi required.
2. **[DISCORDANZA] Policy del ruolo operatore** del connector: le docs riportano `ec2:CreateNetworkInterface` + `ec2:CreateTags` (con condizione); la CLI help dice "`ec2:CreateNetworkInterface`, `ec2:DeleteNetworkInterface` e relative operazioni describe"; lo schema CFN dice "`ec2:CreateNetworkInterface` e relative describe", più `ec2:AllocateAddress`/`ec2:AssociateAddress` se `ElasticIpConfiguration` Type è `ServiceManaged`. Prudenza: includere Create/Delete/Describe NetworkInterface(s), DescribeSubnets/SecurityGroups/Vpcs e CreateTags.
3. **[DISCORDANZA] `ElasticIpConfiguration`** compare nello schema CFN (con definizione vuota) e nella descrizione di OperatorRole, ma non nella CLI 2.39.3 né nelle docs.
4. Range: lo schema CFN non ha massimo per `MaxEnvironments` (docs e CLI: 2-10.000) e per `RateLimit` (docs: valori discreti fino a 10.000; la descrizione CFN elenca gli stessi valori, ma lo schema impone solo minimum 0).
5. Pattern di `Runtime`: CFN `^[a-z][a-z0-9]*[0-9]+(\.[a-z0-9]+)*$`, CLI `[a-z][a-z0-9]*(\.[a-z0-9]+)*`. Irrilevante per `nodejs24.x`.
6. `Name` del NetworkConnector: obbligatorio nella CLI (`--name` required), non required in CFN (probabilmente generato automaticamente) **[AMBIGUO]**.
7. Pattern dei valori in `EnvironmentVariables` di CFN: max 4.096 caratteri per valore; le docs danno un limite aggregato di 32 KB. Non sono in conflitto.
8. Memoria e vCPU: assenti ovunque (coerente con le docs).

## 10. Prezzi di listino eu-west-1 (on-demand, USD)

Fonte primaria: AWS Pricing API (`aws pricing get-products --region us-east-1`), SKU indicati. Interrogata il 2026-10-31.

### Lambda Web Functions (service code AWSLambda)
- Richieste: **$0.30 per milione** ($0.0000003/request), SKU `TZZQMP7YU8CAQPEP`, usagetype `EU-Lambda-Web-Request-ARM`
- vCPU attiva: **$0.0000291572 per vCPU-secondo**, SKU `WWMW8TZJP9FD3R9H`, `EU-Lambda-Web-vCPU-Second-ARM`
- Memoria: **$0.0000038603 per GB-secondo**, SKU `U2U3JV29BSE7BBDX`, `EU-Lambda-Web-Memory-GB-Second-ARM`
- Data transfer: tariffe standard AWS; il traffico verso la VPC è fatturato come "Data Transfer within the same AWS Region". Nessuno SKU specifico. Fonte: https://aws.amazon.com/lambda/pricing/
- Nessun SKU per il NetworkConnector **[NON TROVATO un costo dedicato]**.
- Modello (dalla pagina prezzi, valori US East: $0.0000276944/vCPU-s, $0.0000036667/GB-s): si paga la CPU "attivamente usata" (granularità 1 ms, l'attesa I/O non si paga) e la memoria "consumata da ogni execution environment finché gira, incluso il tempo fra le richieste". Gli esempi usano la memoria consumata (es. 0.49 GB) e non i 2 GB allocati. **[AMBIGUO]**: non è specificato come viene campionata la memoria, se la CPU di init viene fatturata, né se gli environment di headroom inattivi pagano la memoria. Nessun free tier indicato per le Web Functions. Fonte: https://aws.amazon.com/lambda/pricing/
- Stessi prezzi unitari delle Lambda MicroVM (SKU `GQNBX5PTZ9JS4VBJ`, `VB2ZWNFC9YVFGGXQ`).

### Lambda classica (Event Function) arm64
- Richieste: **$0.20 per milione**, SKU `DV2YFXRNHNJFTDP3` (`EU-Request-ARM`)
- Durata: **$0.0000133334 per GB-s** (Tier 1), $0.0000120001 oltre 7,5 miliardi di GB-s/mese, $0.0000106667 oltre 18,75 miliardi; SKU `KXNSA7NBRHBHXXPS` (`EU-Lambda-GB-Second-ARM`)
- (x86 per riferimento: $0.0000166667/GB-s, SKU `SGGKTWDV7PGMPPSJ`)
- Function URL: nessun costo aggiuntivo oltre a richieste e durata **[da pagina prezzi Lambda, non verificato via API: non esiste uno SKU dedicato]**.

### RDS Proxy (AmazonRDS, productFamily `RDSProxy`)
- **$0.016 per vCPU-ora** delle istanze Aurora PostgreSQL associate, SKU `3UKM8N9KQC5QG7KS` (`EU-RDS:ProxyUsage`)
- Minimo di **2 vCPU** per le istanze provisioned; Serverless v2: $0.018/ACU-ora con minimo 8 ACU (SKU `7HGTA8PJ5ZWX2RC2`). Le ore parziali sono fatturate al secondo, con un minimo di 10 minuti dopo un cambio di stato. Fonte: https://aws.amazon.com/rds/proxy/pricing/
- db.t4g.medium ha 2 vCPU, quindi proxy ≈ 2 × $0.016 = **$0.032/ora** per istanza (≈ $23.04 per 30 giorni). **[AMBIGUO]** se writer e reader si sommano: la pagina dice "capacità delle istanze sottostanti" senza dettagli.

### Aurora PostgreSQL db.t4g.medium (Aurora Standard)
- Istanza on-demand: **$0.078/ora**, SKU `M8BZVKDHH2YN9F35` (`EU-InstanceUsage:db.t4g.medium`)
- (I/O-Optimized: $0.101/ora, SKU `RT9CATGARTANK7GQ`)
- Storage Standard: **$0.11 per GB-mese**, SKU `Z57JPT74TUYSYD9G`; I/O: **$0.22 per milione di richieste** ($0.00000022/IO), SKU `NHQEGNNU6EXZ7ZD7`
- (Storage I/O-Optimized: $0.248 per GB-mese, SKU `HDKHJFM3CBX53XUV`, I/O incluso)

### Interface VPC endpoint (AmazonVPC)
- **$0.011 per ora per endpoint per AZ**, SKU `H37WJ97MHYGDXG2A` (`EU-VpcEndpoint-Hours`; lo SKU dice "per VPC Endpoint Hour", mentre la tariffa per AZ è quella della pagina https://aws.amazon.com/privatelink/pricing/)
- Dati elaborati: **$0.01/GB** fino a 1 PB/mese ($0.006 da 1 a 5 PB, $0.004 oltre), SKU `S8CASMMQB4XR7YWZ`

### NAT gateway (AmazonEC2), utile se il connector deve uscire su internet
- $0.048/ora, SKU `KFNSSCHWD43WZK2R`; $0.048/GB elaborato, SKU `DTH8595YVPFXV226`

### EC2 c7g.large Linux on-demand (shared tenancy)
- **$0.0775/ora**, SKU `2R7TNDQ5HPQ9U74T` (`EU-BoxUsage:c7g.large`). 2 vCPU, 4 GiB (da `describe-instance-types`).

### Confronto unitario indicativo (calcolato, non misurato)
- 1 environment Web Function attivo per 1 ora con 2 GB di memoria "consumati" = 2 × 3600 × $0.0000038603 ≈ $0.0278/ora di sola memoria, più la CPU attiva (max 2 vCPU × 3600 s × $0.0000291572 ≈ $0.21/ora se la CPU fosse al 100% su entrambi i core). È solo un ordine di grandezza: i numeri del lab vanno presi dalle esecuzioni reali.

## 2026-10-31 — Codice (senza deploy)

- `cdk synth` ok con `aws-cdk-lib` 2.275.0 e CDK CLI 2.1147.0. Con la CLI 2.1135.1 il synth fallisce: "Cloud assembly schema version mismatch ... at least CLI version 2.1147.0". Pin nel Makefile.
- `@aws-cdk/core:validateAgainstDefaultRules=false` (§2, punto 4): ora i problemi escono come warning, non errori. Sono tutti falsi positivi, con le specifiche locali più vecchie dello schema reale:
  `F3006 Unknown resource type` sui tre tipi WebFunction; `LatestVersionArn is not one of ['Arn','State']` (lo schema reale in eu-west-1 lo ha in readOnlyProperties);
  `AssociatedComputeResourceTypes 'WebFunction' is not one of ['MicroVm']` (lo schema reale ha MicroVm e WebFunction); `EngineVersion '17.11'` non in lista;
  `Tags` non ammesso su `DBProxyTargetGroup` (lo schema reale è taggable).
- Aurora PostgreSQL: l'ultima 17 in eu-west-1 è 17.11; CDK 2.275.0 ha l'enum solo fino a `VER_17_9`, quindi `AuroraPostgresEngineVersion.of("17.11", "17")`.
- Dipendenze circolari tra stack: (1) RDS Proxy aggiunge una regola sul SG del DB che usa la porta del cluster → `sg-db` e `sg-proxy` stanno nel DataStack; (2) `bucket.grant_read_write(loadgen_role)` cross-stack → il permesso S3 del loadgen è scritto nel NetworkStack con il nome del bucket.
- `max_azs=2` con un account fittizio richiede un lookup: AZ fissate (`eu-west-1a`, `eu-west-1b`) e `cdk.context.json` in `.gitignore` (contiene l'ID account).
- CDK non è bootstrappato in eu-west-1 (`CDKToolkit` non esiste): serve `cdk bootstrap` prima del primo deploy.
- Function URL con auth NONE: CDK 2.275.0 genera già sia `lambda:InvokeFunctionUrl` sia `lambda:InvokeFunction` (`InvokedViaFunctionUrl`).
- Endpoint Web Function: nello schema CFN non c'è `AutoDeploymentMode`, quindi `RevisionWeights` = [revisione corrente, 100].
- Codice Web Function: zip con la chiave dell'asset hash sotto `web/`, `BucketDeployment` con `extract=False` e `prune=False` (cancellare l'oggetto dietro una revisione la rompe per sempre). `versionId` non impostato: la chiave è già legata al contenuto.
- Entrypoint: `AWS_LAMBDA_NODEJS_ENTRYPOINT=web/server.mjs` (il runtime carica `index.js` alla radice dello zip). Da verificare nello spike che accetti un `.mjs` in una sottocartella.
- TLS verso Aurora/Proxy: bundle CA RDS (`global-bundle.pem`) dentro lo zip, uguale per le tre varianti.
- Token: secret `lwf-lab-token` generato da CDK, passato alle funzioni come dynamic reference `{{resolve:secretsmanager:...}}` (il valore non è nel template).
- Log group della Web Function creati dallo stack con retention 1 giorno: `/aws/lambda/web/lwf-web-pool` e `.local`.
- Prova locale: `event/index.mjs` risponde 200 su `/health`; `web/server.mjs` con `AWS_LAMBDA_HTTP_ENDPOINT=127.0.0.1:18080` → 200 su `/health`, 401 senza token, 404 su path sconosciuto. Nessuna prova con il DB finora.

### Punti aperti per Gianfranco
1. **Parità di risorse.** Le Web Functions hanno 2 vCPU e 2 GB fissi per ambiente; il piano dà 1024 MB alle Event Functions (circa 0,6 vCPU). Tenere 1024 MB o allinearle?
2. **Primo test sulla Web Function.** Le docs dicono che la concorrenza per ambiente parte bassa e Lambda la impara: il primo test su una funzione nuova usa più ambienti. Serve un run di riscaldamento scartato prima della matrice.
3. **Quote Web Functions dell'account:** 200 vCPU (= 100 ambienti) e 10.000 RPS, contro i default documentati di 2.000 vCPU e 100.000 RPS. Con `maxEnvironments=20` non è un limite.

## 2026-11-02 — Stato quota

- `aws lambda get-account-settings`: `ConcurrentExecutions = 1000`, `UnreservedConcurrentExecutions = 1000`. La richiesta a 1.100 risulta ancora `CASE_OPENED` (ultimo aggiornamento 31/10 10:50), ma il limite effettivo è già passato da 10 a 1.000.
- Con 1.000 non si possono riservare 500 + 500 (AWS tiene sempre 100 non riservate): massimo 450 + 450.

## 2026-11-02 — Bootstrap, budget, spike CLI (§4.1)

- Budget `lwf-lab-20usd` creato (mensile, 20 USD, avvisi ACTUAL > 50% e > 100% a zdotfive@gmail.com).
- `cdk bootstrap aws://<account>/eu-west-1` ok (stack `CDKToolkit`, con tag project=lwf-lab). Resta dopo il lab: non è nella lista di `leftovers.sh`.
- Spike con la CLI, senza VPC, funzione `lwf-spike`, app `node:http` senza dipendenze in `web/spike.mjs`. Tutto cancellato alle 14:37 UTC.
  1. **`create-web-function` senza `--revision-config` e `--endpoint-config` fallisce**: "The revisionConfig and endpointConfig must be specified." La CLI li mostra come opzionali. La funzione nasce insieme alla prima revisione e al primo endpoint.
     In CloudFormation invece `AWS::Lambda::WebFunction` ha solo `FunctionName`: da vedere al deploy come lo gestisce.
  2. Tempi: `create-web-function` risponde in 2 s con funzione Active e revisione/endpoint Pending; revisione Active dopo circa 15 s, endpoint Active subito dopo (waiter `web-function-revision-active` / `web-function-endpoint-active`).
  3. **DNS**: il primo `curl` subito dopo la creazione ha avuto "Could not resolve host"; il resolver di macOS ha tenuto in cache la risposta negativa anche dopo che `dig` risolveva (CNAME su `c300.eu-west-1.prod.frontend.lambda-lite.aws.dev`). Workaround: `curl --resolve host:443:<ip da dig>`.
  4. `AWS_LAMBDA_HTTP_ENDPOINT = 0.0.0.0:3000`. `AWS_LAMBDA_NODEJS_ENTRYPOINT=web/spike.mjs` (`.mjs` in sottocartella) funziona.
  5. Ambiente: Node `v24.22.1`, `arm64`, `os.cpus()` = 2, `os.totalmem()` = 2402 MB, `AWS_LAMBDA_FUNCTION_MEMORY_SIZE=2048`, `AWS_LAMBDA_INITIALIZATION_TYPE=native-http`, `pid` = 2.
     Non c'è `AWS_LAMBDA_FUNCTION_NAME`. Le credenziali del ruolo arrivano come env var (`AWS_ACCESS_KEY_ID`, ...), come nelle Event Functions.
  6. Header aggiunti alla richiesta: `lambda-web-endpoint-name`, `lambda-web-request-id`, `x-forwarded-for/port/proto`. Header di risposta: `lambda-web-logstream: <data>/<fn>[<rev>]<id>` (uno per ambiente) e `lambda-web-request-id`.
  7. Auth `ApplicationManaged`: senza token l'app risponde 401 (la piattaforma non filtra nulla). Latenza dal portatile (Italia) circa 0,27 s a caldo.
  8. **Concorrenza per ambiente che parte bassa**: endpoint con `maxEnvironments=2`, 40 richieste parallele con 1 s di attesa:
     giri 1-5: 4 x 200 e 36 x 429 (`lambda-web-error-type: Platform.EndpointMaxEnvThrottle`), 2 richieste contemporanee per ambiente;
     giro 6: un ambiente sale a 8; giri 7-11: 8 + 8 (16 x 200, 24 x 429); giro 12: uno sale a 20; giri 13-14: 20 + 20, 40 x 200.
     Crescita a gradini 2 → 8 → 20 in circa 15 secondi di traffico. Con un tetto `maxEnvironments` stretto, una funzione nuova rifiuta quasi tutto finché non ha "imparato". Il run di riscaldamento prima della matrice serve.
  9. Log: i log group `/aws/lambda/web/<fn>` e `.local` vengono creati automaticamente senza retention. Eventi `platform.initStart`, `platform.initReport` (con `totalDurationMs`, 257 ms nel primo init, e `instanceId`), `platform.invokeStart`.
     I cold start della Web Function si contano da `platform.initReport`.
  10. Metriche comparse dopo pochi minuti: `AWS/Lambda/Web` `ExecutedRequests`, `HTTPResponseStatusClass4XX` (FunctionName, EndpointName); `AWS/Lambda/Web/Usage` `EndpointActiveEnvironments`, `EndpointActiveEnvironmentThrottles`, `ExecutedRequests` (FunctionName, EndpointName, ExecutionRegion).
  11. `delete-web-function` cancella anche revisioni ed endpoint (stato Deleting, waiter `web-function-deleted` in circa 8 s).

## 2026-11-02 — Deploy, seed, smoke

- `make deploy` (14:59 UTC): LwfNetwork 175 s, LwfData 840 s (Aurora + Proxy). LwfApp fallito alla pubblicazione degli asset:
  `getaddrinfo ENOTFOUND cdk-hnb659fds-assets-<account>-eu-west-1.s3.eu-west-1.amazonaws.com`. `dig` risolveva, il resolver di macOS no
  (cache negativa, come nello spike). Risolto con `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` e nuovo deploy di LwfApp: 321 s.
- **CloudFormation crea la Web Function con il solo `FunctionName`**: la limitazione dell'API (revisione ed endpoint obbligatori alla creazione) in CFN non si vede.
- NetworkConnector `lwf-web-pool-egress` ACTIVE alla versione 1; revisione Active con `egressNetworkConnectorArn` `...:network-connector:nc-<uuid>:1` (l'ARN usa l'ID, non il nome).
- **k6 sul loadgen**: il repo RPM `dl.k6.io` non ha pacchetti aarch64 (404 su `/rpm/aarch64/repodata/repomd.xml`). Installato il binario `k6-v2.3.0-linux-arm64` dal rilascio GitHub; user data corretto nel codice (non ridistribuito su questa istanza).
- Seed (dal loadgen, 16:04-16:06 UTC): 1.000.000 clienti in 12,4 s, 5.000.000 ordini in 141,0 s, indice 5,2 s, totale 2 min 39 s; DB 717 MB. **`max_connections` = 401** su `db.t4g.medium`.
- **Smoke: `event-proxy` → 500 `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`.** Il certificato di RDS Proxy è firmato da Amazon Root CA (ACM), non dalla CA RDS; passare a `pg` solo `global-bundle.pem` sostituisce le CA di sistema.
  Fix uguale per le tre varianti: `ca: [...tls.rootCertificates, global-bundle.pem]`. Nuova revisione Web `rev-ihqlu` (CFN sostituisce la revisione e sposta il peso al 100%).
  Dopo il fix lo smoke passa: stesso JSON per id 1, 4242, 999999 su tutte e tre le varianti.
- `.env` del loadgen: `DB_URL` con `&` non quotato → con `source` la riga va in background e la variabile resta vuota. Valore ora tra apici.
- `pg_stat_activity` a riposo: le connessioni via RDS Proxy arrivano al DB **con l'`application_name` del client** (`lab-event-proxy`) e `client_addr` = IP del Proxy; il Proxy tiene in più connessioni proprie come `rdsproxyadmin`.
  `web-pool` a riposo non ha connessioni: `pg.Pool` chiude le connessioni inattive dopo 10 s (default `idleTimeoutMillis`), il `pg.Client` delle Event Functions resta aperto finché vive l'ambiente.
- SSM Run Command chiude i processi lanciati con `nohup ... &` allo scadere del comando: la matrice gira come unit `systemd-run --unit=lwf-matrix` (avviata 16:14 UTC).
- Shutdown automatico del loadgen spostato da 19:02 a 20:30 UTC per far stare i test aggiuntivi.
- **Matrice bloccata (16:14-16:32 UTC).** Dal primo run di riscaldamento l'agente SSM è andato in `ConnectionLost` e il traffico del loadgen è crollato (da circa 300.000 a 2.000 pacchetti ogni 5 minuti), con k6 al 50% di CPU.
  Causa: in `run.js` l'URL contiene l'id del cliente, quindi k6 crea una serie di metriche per ogni URL (warning: 200.395 → 401.572 → 805.141 → 1.603.144 serie). Memoria esaurita sulla `c7g.large` (4 GB).
  Fix: `tags: { name: 'GET /customer/:id' }` sulla richiesta. Istanza riavviata alle 16:33 UTC (lo shutdown programmato si perde con il reboot: rimesso alle 20:30 UTC). Il run interrotto è scartato.
- **Probe di 30 s su web-pool (16:39 UTC) tutto 401**: `run_one.sh` faceva `source .env` senza esportare, quindi k6 non vedeva `LAB_TOKEN`. Anche il riscaldamento interrotto era fatto solo di 401 (lo smoke passava perché usa `curl` dalla shell). Fix: `set -a; source .env; set +a`.
  Effetto collaterale utile: 200 VU senza attese generano 12.917 req/s di 401; la Web Function risponde con 429 `Platform.AccountRequestThrottle` (93.354), `EndpointRequestThrottle` (8.752), `EndpointMaxEnvThrottle` (6.497) e 26.349 x 503.
  Il limite di account `maxTotalRateLimit` di 10.000 RPS si vede davvero. Questo probe non è un risultato del confronto (solo 401).
- **Matrice 1 (16:39-17:23 UTC) scartata, conservata sul loadgen in `/root/aborted/matrix1`.** Ordine: tre riscaldamenti, poi d0 per event-direct (4 livelli) ed event-proxy (4 livelli).
  Si è fermata al primo run di web-pool (d0, 10 VU): 5.770 richieste, tutte 500. In quel momento Aurora era a 404 `DatabaseConnections` (`max_connections` 401): le teneva gli ambienti Event ancora vivi con il loro `pg.Client` e RDS Proxy (`DatabaseConnections` del Proxy 196, `ClientConnections` 251).
  Il run senza 200 ha fatto uscire `run_one.sh` (`grep` senza righe `ENV` + `pipefail`): corretto.
  **Effetto da riportare nell'articolo**: dopo un picco, gli ambienti Event inattivi tengono aperte le connessioni al DB e RDS Proxy tiene il suo pool (con 0 client il Proxy è rimasto a circa 100 connessioni per oltre mezz'ora). Chi arriva dopo trova il DB pieno.
  `event-proxy` a 500 VU, delay 0: 640 `envId` distinti nelle risposte.
- **Matrice 2, una variante alla volta** (`scripts/orchestrate.sh` dal portatile, avvio 18:08 UTC), ordine event-direct → web-pool → event-proxy (proxy per ultimo per il suo pool inattivo). Prima di ogni blocco:
  riciclo degli ambienti Event (`scripts/reset_envs.py`: cambia la variabile `LAB_RESET`), 60 s di attesa, `pg_terminate_backend` sulle connessioni rimaste dell'utente applicativo, poi riscaldamento (200 VU, delay 100, 2 min) e 8 run.
  Shutdown del loadgen spostato alle 22:00 UTC.

## 2026-11-03/04 — Matrice 2 persa, terza esecuzione

- Il blocco event-direct della matrice 2 è finito alle 18:46 UTC, web-pool è partito alle 18:47 come unit systemd. Poi l'orchestratore sul portatile ha perso SSM (portatile in sospensione, poi token SSO scaduto) e si è fermato in polling; event-proxy non è mai partito.
- **Alle 22:00 UTC il loadgen si è spento con `InstanceInitiatedShutdownBehavior=TERMINATE`**: istanza e disco cancellati, e nessun risultato era stato copiato su S3. Persi matrice 1 (archivio) e matrice 2. Restano solo le metriche CloudWatch.
- Aurora, Proxy ed endpoint VPC sono rimasti accesi circa 23 ore senza traffico. Costo lordo da Cost Explorer (prima dei crediti): 0,12 $ il 1/11, 6,33 $ il 2/11 (Lambda 4,23 $, RDS 1,09 $, EC2 0,54 $, VPC 0,23 $), 0,49 $ parziale il 3/11.
- Correzioni: spegnimento di sicurezza con `STOP` e dopo 8 ore; `run_one.sh` copia ogni run su S3 appena finisce (`RESULTS_BUCKET` in `.env`); il polling dell'orchestratore riprova invece di uscire quando SSM non risponde.
- Loadgen ricreato (4/11, 08:00 UTC). Primo deploy di LwfNetwork fallito: CFN ha provato ad aggiornare l'istanza terminata (`NotFound`). Fix: `user_data_causes_replacement=True`.
- **Terza esecuzione, quella riportata in `results/SUMMARY.md`.** Matrice 08:09-11:08 UTC, picco a freddo 12:56-13:06, pool 14:24-14:47, maxEnvironments 14:49-15:00. 39 run, tutti copiati su S3 alla fine di ognuno.
- Il portatile a batteria va in sospensione anche con `caffeinate -is` (`-s` vale solo con l'alimentatore): due stalli del polling (web-pool → event-proxy circa 57 min, event-proxy → picco a freddo circa 70 min più il `sleep 900` fermo). Il picco a freddo è stato spostato sul loadgen (`/root/cold.sh`, unit `lwf-cold`), il resto rilanciato con l'alimentatore collegato.
- `extras.sh` è uscito al primo run: `$3` senza default in `run_unit` con `set -u`. Corretto con `${3:-}`.
- Osservazioni nuove:
  - web-pool con delay 100 resta su 5 ambienti a 200 VU (circa 40 richieste concorrenti per ambiente): le richieste aspettano una connessione del pool dentro l'ambiente e Lambda non aggiunge ambienti. `POOL_MAX` 5/10/20 → 238/476/893 req/s, ambienti sempre 5.
  - `maxEnvironments` da 20 a 2: per circa 40 s rispondono ancora i 12 ambienti del run precedente (120 connessioni), poi 20 connessioni stabili (2 × `POOL_MAX`). Il client vede 429 `EndpointMaxEnvThrottle`/`EndpointRequestThrottle` e 503.
  - Scenario A: CPU di Aurora 96-98% per almeno 2 minuti a 500 VU in tutte le varianti (criterio di stop del piano raggiunto, run non fermati). p99 di circa 5 s = `connectionTimeoutMillis` 5000.
  - event-proxy d100 v10: 30 richieste in timeout di k6 (60 s) nello stesso secondo, causa non indagata.
  - CloudWatch `DatabaseConnections` di Aurora arriva a 504 con `max_connections` 401: non indagato.
- `results/raw`: URL delle Function URL sostituiti con `<function-url>`, `k6.log` compressi (da 97 MB a 10 MB).
