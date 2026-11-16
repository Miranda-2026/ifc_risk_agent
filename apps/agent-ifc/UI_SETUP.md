# IFC Investment Intelligence UI

The app now serves its IFC interface directly from FastAPI at `/`. It does not
need Node.js, npm, or a separately downloaded chat frontend for normal startup.

## What is implemented

- Opening greeting: **Hi, how can I help you today?**
- **Dashboard** opens `/dashboard`. An unconfigured dashboard shows a placeholder.
- **Quantitative analysis** sends an analysis request to the agent.
- **Recommendation** asks for two Continue and two Review / Reduce clients.
- Each independent recommendation card shows project performance, weighted risk,
  active disbursed exposure, estimated undisbursed exposure, rationale and score.
- **More details** expands scores/contributions, risk metrics, environmental and
  product profiles, qualitative notes, original news links, actions and SQL evidence.
- Scoring weights default to 25% each. Apply & regenerate requests a new ranking
  across the full eligible population and checks the response uses those weights.
- Chat history lives in the current browser tab's memory. Refreshing clears it.
  New conversation clears messages and cancels an in-flight request.

The supplied analytical prompt is preserved in
`agent_server/prompts/ifc_analyst.md`. `agent_server/ui_contract.py` appends the
structured-response contract; `static/cards.js` validates and renders it. Missing
financial values display as unavailable, never as invented zero values.

## Connect the existing Genie Agent

The workspace and Genie Agent supplied for this project are prefilled:

- Workspace: `https://dbc-3e5b0d11-f3e0.cloud.databricks.com`
- Genie Space ID: `01f1ddf25d881906b7234f566362469b`
- Connection: native Databricks SDK Genie Conversation API
  (`/api/2.0/genie/spaces/...`), not the managed MCP endpoint.

The native connection does not require the workspace's **Managed MCP Servers**
Public Preview feature. The previous MCP connection failed because this feature
is disabled in the workspace. The app now obtains real SQL and inline result rows
through the native API. It flags truncated/missing results and never sends signed
download URLs to the model. Each HTTP request owns an isolated Genie conversation.

The Space ID is the segment after `/genie/rooms/` in the supplied URL. The `o`
query parameter identifies the workspace, not the Genie Space. This is a Genie
connection; it does not configure the Dashboard view.

1. To change Genie Agents, open the new Genie Agent in Databricks, select
   **Settings**, and copy **Space ID**.
2. Copy `.env.example` to `.env` if you have not already set up the application.
   Configure your Databricks profile and MLflow experiment as described in README.
3. The current `IFC_GENIE_SPACE_ID` is already populated in `.env.example`.
   Keep the corresponding value in `.env` for local runs.
4. For Bundle deployment, `genie_space_id` defaults to the current Agent. The
   `ifc-genie` resource block in `databricks.yml` requests `CAN_RUN`
   on that Genie Agent. Configure the Databricks identity/resource permissions
   needed by Genie to read the underlying data and use its SQL warehouse.
5. Confirm this Genie Agent contains all three tables:
   - `workspace.ifc_case_comp.project_whole`
   - `workspace.ifc_case_comp.external_news`
   - `workspace.ifc_case_comp.industry_reports`
6. Keep the model endpoint and its `CAN_QUERY` resource consistent. The bundle's
   `llm_endpoint` variable controls both; local runs use `IFC_MODEL_ENDPOINT`.

Credentials stay on the server. Genie queries run with the app's service identity
when deployed; no Databricks access token is exposed to the frontend. The UI does
not modify the Genie Agent or recreate any tables.

If the Genie access check or a query fails, the app returns a safe diagnostic code
and logs the underlying exception. It does not manufacture recommendations. News rows
are research evidence, not automatically a live web search or verified source.

## Permissions for the existing agent-ifc App

For **web UI > From Git** deployment, `databricks.yml` resource declarations are
not applied by the Bundle CLI. Set permissions on the existing App itself:

1. Open **agent-ifc > Settings > Resources**.
2. Add the existing **Genie Agent** with **Can run**.
3. Add each of the three source tables above as **Unity Catalog table** resources
   with **Select**. Ensure the app identity can use the Genie SQL warehouse.
4. For the trace error in the supplied log, add the confirmed table
   `workspace.ifc_case_comp.Project_otel_spans` with **Modify**. App table resources
   also grant the relevant parent catalog/schema usage privileges. Check the
   MLflow experiment's configured trace location and add any other actual trace
   tables it uses (annotations, logs, metrics); do not assume their names.
5. The MLflow experiment resource should allow **Can edit** (or the existing
   higher permission). Redeploy the updated `main` source from `apps/agent-ifc`.

The alternative owner/admin SQL is in `scripts/grant_ifc_app_permissions.sql`.
It targets the existing app client ID `54d0cdaf-97ac-450b-9f91-91d28523704a` and is
not run automatically. A human user's `databricks auth login` does not grant access
to the App's separate service principal. The trace permission failure is separate
from the disabled MCP feature; disabling traces would hide the audit trail rather
than fix either connection.

If the SDK reports only `OperationFailed: ... MessageStatus.FAILED`, it means
Genie accepted the request but failed during processing. That status alone does
not identify a connection, permissions, SQL or warehouse issue. The adapter now
uses the SDK waiter callback to retain Genie's `error.type`, conversation ID and
message ID before the waiter raises its generic error. Recognized schema,
warehouse, SQL, rate-limit and timeout categories receive specific guidance;
unknown categories remain unknown. A redacted detailed reason goes to App Logs.

For the confirmed `USE SCHEMA` failure in the supplied App logs, open Databricks
**SQL Editor > New query** as an owner/admin and run the grant script above. Its
final `SHOW GRANTS` statements verify the App's client ID. These grants are not
executed by committing code or deploying From Git. Separately, open the existing
Genie Agent's **Settings**, identify its SQL warehouse, and ensure this same App
service principal has **Can use** on that warehouse. Re-test a small portfolio
query before requesting the full recommendation analysis.

References: [native Genie API](https://docs.databricks.com/aws/en/genie-agents/conversation-api),
[Genie App resources](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie),
[MLflow App resources](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/mlflow).

## Connect a dashboard later

Set `IFC_DASHBOARD_URL=https://<published-or-embed-url>` in `.env` for local runs,
or the Bundle `dashboard_url` variable for deployment, then restart/redeploy.
For manual Apps deployments, set the corresponding environment values in
`app.yaml` and add the Genie resource in the app settings.

Use a published/embed URL and permissions that allow the intended audience to
view the dashboard. If Databricks blocks iframe display or requires login, use
the **Open in new tab** link. Embedding a dashboard does not give the agent access
to its data; portfolio queries use the Genie connection.

## Run

From `apps/agent-ifc` with the configured project environment:

```sh
uv run start-app
```

Open `http://localhost:8000`. `/invocations` and streaming requests remain
available. The old downloaded frontend is optional via `uv run start-app --legacy-ui`
on `CHAT_APP_PORT`; normal startup uses only the built-in UI at port 8000.

To inspect the layout without dependencies or Databricks credentials:

```sh
python scripts/preview_ui.py --port 8765
```

Open `http://127.0.0.1:8765`. This deliberately shows a preview banner and returns
a clear unavailable message for analysis requests; it contains no fake portfolio
recommendations.

## Checks

```sh
python -m unittest discover -s tests -v
node tests/test_cards.mjs
node tests/test_app.mjs
```

The frontend check uses test-only records. It covers independent cards, incomplete
candidate explanations, distinct clients, ordering, stale weights, score arithmetic,
USD-million formatting and safe text/link rendering. The interaction check runs
the real app module with a minimal DOM adapter to verify navigation, API payloads,
history, weight changes, failures and cancellation. These checks do not verify actual
portfolio calculations. Live model, Genie and dashboard permissions must be checked
in the configured Databricks environment.
