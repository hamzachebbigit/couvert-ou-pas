"use strict"

const LABELS = {
  couvert: "Couvert",
  non_couvert: "Non couvert",
  ambigu: "Ambigu",
  information_insuffisante: "Information insuffisante",
  erreur: "Erreur",
}

const ROW_FIELDS = [
  ["theft_conditions", "Vol : conditions"],
  ["theft_common_areas", "Vol dans les dépendances et locaux communs"],
  ["bike_cap", "Plafond vélo"],
  ["jewellery_cap", "Plafond bijoux"],
  ["deductible_general", "Franchise générale"],
  ["unoccupancy_limit", "Inoccupation tolérée"],
  ["heat_without_fire_excluded", "Chaleur sans incendie"],
  ["contents_outside_building", "Biens hors du bâtiment"],
  ["accidental_damage_option", "Option tous risques"],
]

const state = { contracts: [], clauses: {}, contractId: null }

const $ = (id) => document.getElementById(id)

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value
    else if (key === "text") node.textContent = value
    else if (key === "html") node.innerHTML = value
    else node.setAttribute(key, value)
  }
  for (const child of children) node.append(child)
  return node
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
}

function fmtConfidence(value) {
  return `confiance ${Number(value).toFixed(2).replace(".", ",")}`
}

async function api(path, options) {
  const response = await fetch(path, options)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.detail || body.error || `Erreur ${response.status}`
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail))
  }
  return body
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name))
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("is-active", panel.id === `tab-${name}`))
  if (name === "evaluation") loadEval()
}

function renderContractRow(contract) {
  const box = $("contract-row")
  box.innerHTML = ""
  if (!contract) return
  const head = el("div", { class: "row-head", text: `${contract.insurer}, ${contract.product}, ${contract.edition || "édition non datée"}, ${contract.pages} pages` })
  box.append(head)
  const meta = el("p", { class: "hint", text: `${contract.clauses} clauses, ${contract.table_rows} rangées de tableau.` })
  box.append(meta)
  const row = contract.row
  if (!row) {
    box.append(el("p", { class: "none", text: "Ligne structurée non encore extraite pour ce contrat." }))
    return
  }
  const dl = el("dl")
  dl.append(el("dt", { text: "Familles de garanties présentes" }))
  const fams = el("dd", { class: "fams" })
  for (const f of row.guarantee_families) fams.append(el("span", { text: f.replace(/_/g, " ") }))
  dl.append(fams)
  for (const [key, label] of ROW_FIELDS) {
    const value = row[key]
    dl.append(el("dt", { text: label }))
    dl.append(el("dd", {}, [citedValue(value)]))
  }
  if (row.notable_exclusions && row.notable_exclusions.length) {
    dl.append(el("dt", { text: "Exclusions notables" }))
    const ul = el("ul")
    for (const item of row.notable_exclusions) ul.append(el("li", {}, [citedValue(item)]))
    dl.append(el("dd", {}, [ul]))
  }
  box.append(dl)
}

function citedValue(value) {
  if (!value || !value.value) return el("span", { class: "none", text: "non trouvé dans le contrat" })
  const span = el("span", { class: "cite", tabindex: "0", text: value.value })
  const where = value.page ? `Page ${value.page}` : "Page inconnue"
  const quote = value.quote ? `« ${value.quote} »` : "Citation non vérifiée."
  span.append(el("span", { class: "tip", text: `${where}. ${quote}` }))
  return span
}

function renderVerdict(data) {
  state.clauses = data.clauses || {}
  const v = data.verdict
  $("result").hidden = false
  const card = $("card")
  card.className = `card ${v.verdict}`
  $("verdict-label").textContent = LABELS[v.verdict] || v.verdict
  $("confidence").textContent = fmtConfidence(v.confidence)
  $("summary").textContent = v.summary

  const missing = $("missing")
  const missingList = $("missing-list")
  missingList.innerHTML = ""
  missing.hidden = !(v.missing_facts && v.missing_facts.length)
  for (const fact of v.missing_facts || []) missingList.append(el("li", { text: fact }))

  $("alternative").hidden = !v.alternative_reading
  $("alternative-text").textContent = v.alternative_reading || ""

  const ifthen = $("ifthen")
  const ifthenList = $("ifthen-list")
  ifthenList.innerHTML = ""
  ifthen.hidden = !(v.if_then && v.if_then.length)
  for (const line of v.if_then || []) ifthenList.append(el("li", { text: line }))

  const amounts = $("amounts")
  amounts.innerHTML = ""
  const pairs = [["Plafond", v.cap], ["Franchise", v.deductible]].filter(([, c]) => c && c.value)
  amounts.hidden = pairs.length === 0
  for (const [label, cited] of pairs) {
    const box = el("div", { class: "amount" })
    box.append(el("b", { text: label }))
    box.append(document.createTextNode(cited.value + (cited.page ? ` (page ${cited.page})` : "")))
    amounts.append(box)
  }

  const notes = $("notes")
  notes.hidden = !(v.notes && v.notes.length)
  notes.textContent = (v.notes || []).join(" ")

  const cited = $("cited")
  cited.innerHTML = ""
  if (!v.cited.length) {
    cited.append(el("li", { class: "empty", text: v.verdict === "information_insuffisante" ? "Aucune clause ne peut être citée tant que les faits manquants ne sont pas connus." : "Aucune clause citée." }))
  }
  for (const c of v.cited) {
    const li = el("li", { "data-clause": c.clause_id, "data-quote": c.quote })
    const head = el("div")
    head.append(el("span", { class: "role", text: c.role }))
    head.append(el("strong", { text: c.title || c.clause_id }))
    head.append(el("span", { class: "where", text: `, page ${c.page}` }))
    li.append(head)
    li.append(el("blockquote", { text: `« ${c.quote} »` }))
    li.addEventListener("click", () => openClause(c.clause_id, c.quote, c.page))
    cited.append(li)
  }

  const reasoning = $("reasoning")
  reasoning.innerHTML = ""
  for (const step of v.reasoning || []) reasoning.append(el("li", { text: step }))

  renderTrace(data.trace)
}

function renderTrace(t) {
  const parts = []
  parts.push(t.cache_hit ? "réponse servie depuis le cache" : "nouvelle analyse")
  if (t.parsed) parts.push(`familles : ${t.parsed.event_family.join(", ")}`)
  parts.push(`${t.candidates_after_filter} clauses après filtre`)
  parts.push(`${t.candidates_after_fusion} après fusion`)
  parts.push(`${t.candidates_after_rerank} retenues`)
  if (t.total_ms) parts.push(`${(t.total_ms / 1000).toFixed(1).replace(".", ",")} s`)
  $("trace-line").textContent = `Comment le verdict a été produit : ${parts.join(" → ")}`
  const body = $("trace-body")
  body.innerHTML = ""
  if (t.parsed) {
    body.append(el("p", { text: `Lecture typée : événement « ${t.parsed.event} », objet « ${t.parsed.object || "aucun"} », lieu « ${t.parsed.place || "aucun"} ».` }))
    if (t.parsed.facts_potentially_needed.length) body.append(el("p", { text: `Faits exigés et absents : ${t.parsed.facts_potentially_needed.join(" / ")}` }))
  }
  if (t.retrieved && t.retrieved.length) {
    const table = el("table")
    table.append(el("thead", { html: "<tr><th>Clause</th><th>Pages</th><th>BM25</th><th>Embed.</th><th>Arbitre</th></tr>" }))
    const tbody = el("tbody")
    for (const r of t.retrieved) {
      const tr = el("tr")
      tr.append(el("td", { text: `${r.path}${r.always_included ? " (toujours incluse)" : ""}` }))
      tr.append(el("td", { text: `${r.page_start}${r.page_end !== r.page_start ? ` à ${r.page_end}` : ""}` }))
      tr.append(el("td", { text: r.bm25_rank ?? "" }))
      tr.append(el("td", { text: r.embed_rank ?? "" }))
      tr.append(el("td", { text: r.rerank_score ?? "" }))
      tbody.append(tr)
    }
    table.append(tbody)
    body.append(table)
  }
  const models = Object.entries(t.models || {}).map(([k, v]) => `${k} : ${v}`).join(", ")
  const timings = (t.timings || []).map((s) => `${s.stage} ${s.ms} ms`).join(", ")
  body.append(el("pre", { text: [models && `Modèles : ${models}`, timings && `Durées : ${timings}`, t.post_checks.length && `Vérifications : ${t.post_checks.join(" / ")}`, `Prompts : ${t.prompt_version}`].filter(Boolean).join("\n") }))
}

async function openClause(clauseId, quote, page) {
  let clause = state.clauses[clauseId]
  if (!clause) {
    try {
      clause = await api(`/api/clause/${encodeURIComponent(state.contractId)}/${encodeURIComponent(clauseId)}`)
    } catch (error) {
      clause = { title: clauseId, path: "", page_start: page, page_end: page, text: quote }
    }
  }
  $("clause-title").textContent = clause.number ? `${clause.number} ${clause.title}` : clause.title
  const pages = clause.page_start === clause.page_end ? `page ${clause.page_start}` : `pages ${clause.page_start} à ${clause.page_end}`
  $("clause-meta").textContent = `${clause.path} (${pages}, passage cité page ${page})`
  const body = $("clause-text")
  const text = clause.text || ""
  const index = quote ? text.indexOf(quote) : -1
  if (index >= 0) {
    body.innerHTML = `${escapeHtml(text.slice(0, index))}<mark>${escapeHtml(quote)}</mark>${escapeHtml(text.slice(index + quote.length))}`
  } else {
    body.innerHTML = escapeHtml(text)
  }
  $("clause-modal").hidden = false
  const mark = body.querySelector("mark")
  if (mark) mark.scrollIntoView({ block: "center" })
}

function closeClause() {
  $("clause-modal").hidden = true
}

async function analyse(event) {
  event.preventDefault()
  const question = $("question").value.trim()
  const contractId = $("contract").value
  if (!question || !contractId) return
  state.contractId = contractId
  const button = $("submit")
  const status = $("status")
  button.disabled = true
  status.className = "status"
  status.textContent = "Analyse en cours, une dizaine de secondes pour une question nouvelle."
  try {
    const data = await api("/api/analyse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contract_id: contractId, question }) })
    status.textContent = ""
    renderVerdict(data)
    $("result").scrollIntoView({ behavior: "smooth", block: "start" })
  } catch (error) {
    status.className = "status is-error"
    status.textContent = error.message
  } finally {
    button.disabled = false
  }
}

async function loadEval() {
  const summaryBox = $("eval-summary")
  if (summaryBox.dataset.loaded) return
  const data = await api("/api/eval")
  summaryBox.dataset.loaded = "1"
  summaryBox.innerHTML = ""
  const tbody = document.querySelector("#eval-table tbody")
  tbody.innerHTML = ""
  if (!data.summary) {
    summaryBox.append(el("p", { class: "hint", text: "L'évaluation n'a pas encore été lancée." }))
    return
  }
  const s = data.summary
  const pct = (x) => (x == null ? "n/a" : `${Math.round(x * 100)} %`)
  const stats = [
    ["Questions", s.n, ""],
    ["Exactitude du verdict", pct(s.accuracy), ""],
    ["Clause attendue citée", pct(s.citation_hit.rate), ""],
    ["Faux « couvert »", s.false_covered.n, "danger"],
    ["Faux « non couvert »", s.false_not_covered.n, "warn"],
    ["Abstentions", `${s.abstention.n} (${pct(s.abstention.rate)})`, ""],
    ["Abstentions justifiées", pct(s.abstention.justified_rate), ""],
  ]
  for (const [label, value, kind] of stats) {
    const box = el("div", { class: `stat ${kind}` })
    box.append(el("div", { class: "n", text: value }))
    box.append(el("div", { class: "l", text: label }))
    summaryBox.append(box)
  }
  const perClass = el("div", { class: "stat" })
  perClass.append(el("div", { class: "l", text: "Exactitude par classe attendue" }))
  for (const [label, c] of Object.entries(s.per_class)) {
    perClass.append(el("div", { text: `${LABELS[label]} : ${c.correct}/${c.n}` }))
  }
  summaryBox.append(perClass)
  const names = Object.fromEntries(state.contracts.map((c) => [c.id, `${c.insurer} ${c.product}`]))
  for (const item of data.items) {
    const tr = el("tr", { class: item.obtained_verdict === item.expected_verdict ? "" : "miss" })
    tr.append(el("td", { text: item.id }))
    tr.append(el("td", { text: names[item.contract_id] || item.contract_id }))
    tr.append(el("td", { text: item.question }))
    tr.append(el("td", {}, [el("span", { class: `pill ${item.expected_verdict}`, text: LABELS[item.expected_verdict] })]))
    tr.append(el("td", {}, [el("span", { class: `pill ${item.obtained_verdict}`, text: LABELS[item.obtained_verdict] || item.obtained_verdict })]))
    tr.append(el("td", { text: item.citation_hit == null ? "sans objet" : item.citation_hit ? "oui" : "non" }))
    tr.append(el("td", { text: item.confidence == null ? "" : Number(item.confidence).toFixed(2).replace(".", ",") }))
    tbody.append(tr)
  }
}

async function init() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)))
  $("form").addEventListener("submit", analyse)
  $("clause-close").addEventListener("click", closeClause)
  $("clause-modal").addEventListener("click", (event) => { if (event.target === $("clause-modal")) closeClause() })
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeClause() })

  const select = $("contract")
  try {
    state.contracts = await api("/api/contracts")
  } catch (error) {
    $("status").className = "status is-error"
    $("status").textContent = error.message
    return
  }
  for (const c of state.contracts) {
    select.append(el("option", { value: c.id, text: `${c.insurer}, ${c.product} (${c.edition || "s.d."})` }))
  }
  select.addEventListener("change", () => renderContractRow(state.contracts.find((c) => c.id === select.value)))
  renderContractRow(state.contracts[0])

  const examples = await api("/api/examples").catch(() => [])
  const chips = $("examples")
  for (const ex of examples.slice(0, 6)) {
    const chip = el("button", { type: "button", class: "chip", text: ex.question.length > 48 ? `${ex.question.slice(0, 46)}…` : ex.question, title: ex.question })
    chip.addEventListener("click", () => { $("question").value = ex.question })
    chips.append(chip)
  }
}

init()
