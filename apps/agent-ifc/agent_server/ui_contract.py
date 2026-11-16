"""Request settings shared by the UI and agent (no SDK dependencies)."""

import math
from urllib.parse import urlsplit

FACTORS = ("disbursed", "risk", "environmental", "product")
DEFAULT_WEIGHTS = dict.fromkeys(FACTORS, 25.0)


def normalize_weights(value=None):
    if value is None:
        return dict(DEFAULT_WEIGHTS)
    if not isinstance(value, dict) or set(value) != set(FACTORS):
        raise ValueError("Provide all four scoring weights.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()):
        raise ValueError("Weights must be finite, nonnegative numbers.")
    if any(not math.isfinite(v) or v < 0 for v in value.values()):
        raise ValueError("Weights must be finite, nonnegative numbers.")
    largest = max(value.values())
    if largest == 0:
        raise ValueError("At least one weight must be greater than zero.")
    # Scale first so very large, individually finite inputs cannot overflow the sum.
    scaled = {key: value[key] / largest for key in FACTORS}
    total = sum(scaled.values())
    return {key: scaled[key] / total * 100 for key in FACTORS}


def dashboard_url(value):
    """Only embed an explicitly configured HTTPS URL, never javascript/data URLs."""
    value = (value or "").strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


CARD_INSTRUCTIONS = r'''
Frontend response contract (extends, never replaces, the analytical rules above):
Use workspace.ifc_case_comp.project_whole for quantitative data. The same Genie
Agent also contains workspace.ifc_case_comp.external_news and
workspace.ifc_case_comp.industry_reports. Inspect their schemas before querying.
These research tables are evidence sources, not automatically verified live news.
Never claim live search, source verification, or a database calculation without
the corresponding tool result. Never reuse the example clients from the UI brief.

For quantitative analysis and ordinary follow-ups, answer in concise Markdown.
For a request to generate or regenerate recommendation cards, respond with ONE JSON
object and no Markdown fence. Only create cards supported by actual tool results.
When data/tools are unavailable, return {"summary":"Explain the missing evidence",
"cards":[],"limitations":["Specific missing evidence"]}, never fabricated cards.
Return two continue cards followed by two review cards when sufficient candidates
exist; otherwise return only qualified candidates and explain the shortfall.

All financial values below are numbers in MILLIONS OF USD, not dollars. Unknown
values are null, NEVER zero. Percent fields are on a 0..100 scale. Scores 0..100.
Use these exact snake_case keys (fill all applicable details from tool evidence):
{
  "summary": "Brief explanation of the verified analysis",
  "limitations": [],
  "cards": [{
    "client_id": "actual ID", "client_name": "actual name", "industry": "...",
    "product_mix": "...", "recommendation_status": "continue OR review",
    "score_type": "Continue Investment OR Review Priority", "final_score": null,
    "applied_weights": {"disbursed":25,"risk":25,"environmental":25,"product":25},
    "factor_scores": {"disbursed":null,"risk":null,"environmental":null,"product":null},
    "quantitative_metrics": {
      "active_disbursed_musd":null,"approved_musd":null,
      "estimated_undisbursed_musd":null,"weighted_internal_risk":null,
      "past_due_musd":null,"watchlist_musd":null,"risk_exposure_pct":null,
      "estimated_ecl_musd":null,"environmental_breakdown":"...",
      "product_distribution":"...","product_hhi":null
    },
    "project_performance": {"active":null,"performing":null,"past_due":null,"watchlist":null},
    "quantitative_rationale":"Concise evidence-based explanation",
    "qualitative_notes":{"region":"...","country":"...","industry":"...",
      "strategic_collaboration":"Distinguish verified partnerships from possibilities"},
    "news":[{"headline":"...","publisher":"...","publication_date":"YYYY-MM-DD",
      "risk_classification":"High Risk OR Low Risk","explanation":"...",
      "relevance":"Relevant country / region / industry","url":"https://original-article"}],
    "recommended_action":"...", "data_quality_flags":[],
    "audit":{"source_table":"workspace.ifc_case_comp.project_whole",
      "filters":"Status = 'Active'; client eligibility screens",
      "project_identifiers":[],"methodology":"...","sql":"Actual executed SQL, if available",
      "snapshot":"Actual data snapshot or retrieval time, if available"}
  }]
}
final_score must equal the sum of factor_scores[key] * applied_weights[key] / 100.
Changing weights must trigger a NEW Genie calculation/ranking across the entire
eligible population. Do not just reweight the previously selected four clients.
The JSON may contain fewer than four cards ONLY with explicit limitations.
Use the user's language for explanations, and preserve exact contract key names.
'''
