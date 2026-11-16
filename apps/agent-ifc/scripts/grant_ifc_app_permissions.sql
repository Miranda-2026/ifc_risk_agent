-- Run only as the catalog/schema/table owner or an authorized administrator.
-- This file is a reviewable grant script; the application does not execute it.
-- The grantee is agent-ifc's application/client ID from the deployed App log.
-- Settings > Resources in the App UI is also a supported way to grant access.

GRANT USE CATALOG ON CATALOG workspace
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

GRANT USE SCHEMA ON SCHEMA workspace.ifc_case_comp
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

GRANT SELECT ON TABLE workspace.ifc_case_comp.project_whole
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

GRANT SELECT ON TABLE workspace.ifc_case_comp.external_news
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

GRANT SELECT ON TABLE workspace.ifc_case_comp.industry_reports
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

-- This table is confirmed by the error log. Do not guess other table names.
GRANT SELECT, MODIFY ON TABLE workspace.ifc_case_comp.Project_otel_spans
TO `54d0cdaf-97ac-450b-9f91-91d28523704a`;

-- Also add the actual Genie Agent to agent-ifc Settings > Resources with Can run.
-- Grant Can use on the SQL warehouse used by Genie where required.
-- For complete MLflow UC tracing, check the experiment's configured trace table
-- location and grant SELECT, MODIFY on each actual annotations/logs/metrics/spans
-- table it uses. Do not grant broad schema-wide write privileges.
