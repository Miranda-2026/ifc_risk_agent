// Pure rendering helpers: all model-provided text is escaped before entering HTML.
export const FACTORS = ['disbursed', 'risk', 'environmental', 'product'];
export const FACTOR_NAMES = ['Disbursed amount', 'Internal risk', 'Environmental', 'Product line'];
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const numeric = value => typeof value === 'number' && Number.isFinite(value);
export const number = (value, decimals = 2) => numeric(value) ? value.toLocaleString('en-US', {minimumFractionDigits:decimals, maximumFractionDigits:decimals}) : '—';
export const money = value => numeric(value) ? `$${number(value)}M` : '—';
export const count = value => number(value, 0);
export function safeUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}
export function normalizeWeights(weights) {
  if (!weights || FACTORS.some(k => !numeric(weights[k]) || weights[k] < 0)) throw new Error('Enter a nonnegative number for every factor.');
  const largest = Math.max(...FACTORS.map(k => weights[k]));
  if (!largest) throw new Error('At least one weight must be greater than zero.');
  const total = FACTORS.reduce((sum,k) => sum + weights[k] / largest, 0);
  return Object.fromEntries(FACTORS.map(k => [k, weights[k] / largest / total * 100]));
}
export function responseText(response) {
  return (response.output || []).filter(item => item.type === 'message' && item.role === 'assistant').flatMap(item => typeof item.content === 'string' ? [item.content] : (item.content || []).filter(p => p.type === 'output_text').map(p => p.text || '')).join('\n');
}
export function parseAnswer(text, requestedWeights) {
  const candidate = text.trim().replace(/^```(?:json|ifc-recommendations)?\s*\n?/i, '').replace(/\n?```\s*$/, '');
  let data;
  try { data = JSON.parse(candidate); } catch { return {text}; }
  if (!data || !Array.isArray(data.cards)) return {text};
  if (data.summary !== undefined && typeof data.summary !== 'string') throw new Error('The response summary must be text.');
  if (data.limitations !== undefined && (!Array.isArray(data.limitations) || data.limitations.some(item=>typeof item!=='string'))) throw new Error('Response limitations must be a list of explanations.');
  if (data.cards.length > 4) throw new Error('The response contains more than four recommendation cards.');
  if (data.cards.length < 4 && !data.limitations?.length) throw new Error('The agent must explain why fewer than four clients qualify.');
  const ids = new Set(); let continues = 0; let reviews = 0; let seenReview = false;
  for (const card of data.cards) {
    if (!card || typeof card.client_id!=='string' || typeof card.client_name!=='string' || !card.client_id.trim() || !card.client_name.trim() || ids.has(card.client_id)) throw new Error('Client names and distinct client IDs are required.');
    ids.add(card.client_id);
    if (card.recommendation_status === 'continue') { continues++; if (seenReview) throw new Error('Continue cards must precede review cards.'); }
    else if (card.recommendation_status === 'review') { reviews++; seenReview = true; }
    else throw new Error('The recommendation status must be continue or review.');
    if (continues > 2 || reviews > 2) throw new Error('At most two clients qualify in each recommendation category.');
    if (!numeric(card.final_score) || card.final_score < 0 || card.final_score > 100) throw new Error('A verified final score between 0 and 100 is required.');
    const weights = card.applied_weights, scores = card.factor_scores;
    if (!weights || !scores || FACTORS.some(k => !numeric(weights[k]) || weights[k] < 0 || !numeric(scores[k]) || scores[k] < 0 || scores[k] > 100)) throw new Error('All four factor scores and applied weights are required.');
    if (Math.abs(FACTORS.reduce((s,k) => s + weights[k], 0) - 100) > .05) throw new Error('Applied weights do not total 100%.');
    if (requestedWeights && FACTORS.some(k => Math.abs(weights[k] - requestedWeights[k]) > .05)) throw new Error('The result does not use your latest scoring weights. Please regenerate.');
    const computed = FACTORS.reduce((sum,k) => sum + scores[k] * weights[k] / 100, 0);
    if (Math.abs(computed - card.final_score) > .15) throw new Error('The final score does not match the four weighted contributions.');
  }
  return data;
}

const icon = name => `<svg class="icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
const metric = (label, value, caption='') => `<div><span class="metric-label">${escapeHtml(label)}</span><span class="metric-value">${value}</span>${caption ? `<span class="metric-caption">${escapeHtml(caption)}</span>` : ''}</div>`;
const textValue = value => typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? 'Not available');
const detailLine = (label,value) => `<p><strong>${escapeHtml(label)}:</strong> ${escapeHtml(textValue(value))}</p>`;
const detailSection = (title,body) => `<section class="detail-section"><h3>${escapeHtml(title)}</h3>${body}</section>`;

export function renderCard(card, index) {
  const review = card.recommendation_status === 'review';
  const metrics = card.quantitative_metrics || {}, performance = card.project_performance || {}, notes = card.qualitative_notes || {}, audit = card.audit || {};
  const status = review ? 'Review / Reduce' : 'Continue';
  const scoreType = review ? 'Review Priority' : 'Continue Investment';
  const performanceValue = review ? `${count(performance.past_due)} <span class="metric-unit">/</span> ${count(performance.watchlist)}` : `${count(performance.performing)} <span class="metric-unit">/</span> ${count(performance.active)}`;
  const rows = FACTORS.map((key,i) => `<tr><td>${FACTOR_NAMES[i]}</td><td>${number(card.factor_scores[key])}</td><td>${number(card.applied_weights[key],1)}%</td><td>${number(card.factor_scores[key]*card.applied_weights[key]/100)}</td></tr>`).join('');
  const scoreTable = `<table class="factor-table"><thead><tr><th scope="col">Factor</th><th scope="col">Score / 100</th><th scope="col">Weight</th><th scope="col">Contribution</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td colspan="3">${scoreType} Score</td><td>${number(card.final_score)}</td></tr></tfoot></table>`;
  const riskMetrics = `<div class="detail-metrics">${metric('Approved investment',money(metrics.approved_musd))}${metric('Past Due exposure',money(metrics.past_due_musd))}${metric('Watchlist exposure',money(metrics.watchlist_musd))}${metric('Risk exposure ratio',numeric(metrics.risk_exposure_pct)?`${number(metrics.risk_exposure_pct)}%`:'—')}${review?metric('Estimated ECL',money(metrics.estimated_ecl_musd),'Case assumption: 60% × Past Due exposure'):''}${metric('Active / Performing / Past Due / Watchlist',`${count(performance.active)} / ${count(performance.performing)} / ${count(performance.past_due)} / ${count(performance.watchlist)}`)}</div><p>Financial values are in USD millions. Estimated undisbursed amounts may differ from contractual commitments.</p>`;
  const news = Array.isArray(card.news) ? card.news.filter(article=>article && typeof article==='object') : [];
  const newsHtml = news.length ? news.map(article => {
    const url = safeUrl(article.url);
    return `<article class="news-item">${url?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.headline)} ↗</a>`:`<strong>${escapeHtml(article.headline)}</strong>`}<small>${escapeHtml(article.publisher || 'Publisher unavailable')} · ${escapeHtml(article.publication_date || 'Date unavailable')}</small>${['High Risk','Low Risk'].includes(article.risk_classification)?`<span class="news-risk ${article.risk_classification==='High Risk'?'high':''}">${escapeHtml(article.risk_classification)}</span>`:''}<p>${escapeHtml(article.explanation)}</p>${article.relevance?`<p>${escapeHtml(article.relevance)}</p>`:''}${!url?'<p>Original source link unavailable.</p>':''}</article>`;
  }).join('') : '<p>No verified news was provided for this client.</p>';
  const flags = Array.isArray(card.data_quality_flags) && card.data_quality_flags.length ? `<div class="flags">${card.data_quality_flags.map(flag=>`<p>${escapeHtml(flag)}</p>`).join('')}</div>` : '';
  const auditHtml = `<details class="audit"><summary>Source, methodology & SQL</summary>${detailLine('Source',audit.source_table)}${detailLine('Filters',audit.filters)}${detailLine('Snapshot',audit.snapshot)}${detailLine('Methodology',audit.methodology)}${detailLine('Project identifiers',Array.isArray(audit.project_identifiers)?audit.project_identifiers.join(', '):audit.project_identifiers)}<pre>${escapeHtml(audit.sql || 'Executed SQL was not included in this response.')}</pre></details>`;
  return `<article class="client-card ${review?'is-review':''}" aria-label="${escapeHtml(card.client_name)} — ${status}"><div class="card-main"><div class="card-header"><div><h2><span class="card-number">${index+1}.</span>${escapeHtml(card.client_name)}</h2><p class="card-meta">${escapeHtml(card.client_id)} · ${escapeHtml(card.industry || notes.industry || 'Industry unavailable')}${card.product_mix?` · ${escapeHtml(card.product_mix)}`:''}</p></div><span class="status-badge ${review?'review':''}">${status}</span></div><div class="metric-grid">${metric(review?'Past Due / Watchlist':'Active Project Performance',performanceValue,review?'Projects requiring attention':'Performing / Active projects')}${metric('Weighted Internal Risk',`${number(metrics.weighted_internal_risk)} <span class="metric-unit">/ 6</span>`,'1 = lowest risk · 6 = highest risk')}${metric('Disbursed Amount',money(metrics.active_disbursed_musd))}${metric('Est. Undisbursed',money(metrics.estimated_undisbursed_musd))}</div><p class="card-rationale"><strong>${review?'Review rationale':'Recommendation rationale'}:</strong> ${escapeHtml(card.quantitative_rationale || 'Rationale was not provided.')}</p><div class="score-line"><span>${scoreType} Score</span><span class="score-track"><span style="width:${card.final_score}%"></span></span><strong>${number(card.final_score)} <span class="metric-unit">/ 100</span></strong></div></div><details class="card-details"><summary><span>More details</span>${icon('chevron')}</summary><div class="details-content">${detailSection('Quantitative score breakdown',scoreTable)}${detailSection('Risk & exposure',riskMetrics)}${detailSection('Environmental & product profile',detailLine('Environmental categories',metrics.environmental_breakdown)+detailLine('Product distribution',metrics.product_distribution)+detailLine('Product concentration (HHI)',numeric(metrics.product_hhi)?number(metrics.product_hhi,4):null)+'<p>Product diversification is an analytical concentration proxy, not an official IFC product-risk rating.</p>')}${detailSection('Additional notes · qualitative research',detailLine('Region',notes.region)+detailLine('Country',notes.country)+detailLine('Industry',notes.industry)+detailLine('Strategic collaboration',notes.strategic_collaboration))}${detailSection('External research',newsHtml)}${detailSection('Recommended action',`<p class="card-action">${escapeHtml(card.recommended_action || 'Further human review is required.')}</p>`)}${detailSection('Evidence & limitations',auditHtml+flags+'<p>Subject to human review. Scores are decision-support indicators, not guarantees of future performance.</p>')}</div></details></article>`;
}

// Small, dependency-free Markdown subset. Raw HTML and model-provided images are
// never rendered. Tables/fenced SQL remain readable even without a CDN library.
export function renderMarkdown(text) {
  const inline = value => escapeHtml(value).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  let code = false, codeLines = [], list = false, output = [];
  const closeList = () => { if (list) { output.push('</ul>'); list = false; } };
  for (const line of String(text).split('\n')) {
    if (/^```/.test(line)) { closeList(); if (code) { output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);codeLines=[]; } code=!code;continue; }
    if (code) {codeLines.push(line);continue;}
    const heading = line.match(/^#{1,4}\s+(.+)/), bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);
    if (heading) {closeList();output.push(`<h3>${inline(heading[1])}</h3>`);}
    else if (bullet) {if (!list) {output.push('<ul>');list=true;}output.push(`<li>${inline(bullet[1])}</li>`);}
    else {closeList();if (line.trim()) output.push(`<p>${inline(line)}</p>`);}
  }
  closeList();if(codeLines.length) output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
  return output.join('');
}
