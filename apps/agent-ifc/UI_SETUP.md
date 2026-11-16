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
- Server-side MCP endpoint:
  `https://dbc-3e5b0d11-f3e0.cloud.databricks.com/api/2.0/mcp/genie/01f1ddf25d881906b7234f566362469b`

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

Credentials stay on the server. MCP tools run with the app's service identity
when deployed; no Databricks access token is exposed to the frontend. The UI does
not modify the Genie Agent or recreate any tables.

If the Genie connection is missing or cannot list its tools, the app returns an
explicit connection message and does not manufacture recommendations. News rows
are research evidence, not automatically a live web search or verified source.

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
