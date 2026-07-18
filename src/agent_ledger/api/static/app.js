"use strict";

const token = document.querySelector('meta[name="agent-ledger-token"]').content;
const authHeaders = { "X-Agent-Ledger-Token": token };
const state = {
  catalog: null,
  candidates: [],
  filter: "all",
  selectedButton: null,
  continuationPrompt: "",
  mode: "catalog"
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clear(target) {
  target.replaceChildren();
}

function evidenceText(ids) {
  return ids.length ? `EVIDENCE / ${ids.join(" · ")}` : "EVIDENCE / NONE";
}

function addFact(list, label, value) {
  const wrapper = element("div", "fact");
  wrapper.append(element("dt", "", label), element("dd", "", value));
  wrapper.querySelector("dd").translate = false;
  wrapper.title = value;
  list.append(wrapper);
}

function renderSignal(target, item, index) {
  const row = element("li");
  row.dataset.marker = String(index + 1).padStart(2, "0");
  row.append(element("span", "", item.statement));
  row.append(element("div", "evidence-link", evidenceText(item.evidence_ids)));
  target.append(row);
}

function resetBrief() {
  [
    "#session-facts",
    "#recorded-observations",
    "#current-observations",
    "#uncertainties",
    "#readiness-grid",
    "#actions",
    "#evidence-grid"
  ].forEach((selector) => clear(document.querySelector(selector)));
  state.continuationPrompt = "";
  document.querySelector("#copy-prompt").disabled = true;
  document.querySelector("#copy-status").textContent = "";
}

function renderBrief(brief) {
  resetBrief();
  const facts = document.querySelector("#session-facts");
  addFact(facts, "SESSION", brief.session_id);
  addFact(facts, "PROJECT", brief.project);
  addFact(facts, "BRANCH", brief.branch);
  addFact(facts, "HEAD", brief.head.slice(0, 12));
  addFact(facts, "ADAPTER", `${brief.source_adapter.name}@${brief.source_adapter.version}`);

  document.querySelector("#intent").textContent = brief.intent;
  const recorded = document.querySelector("#recorded-observations");
  const current = document.querySelector("#current-observations");
  brief.observations.forEach((item, index) => {
    renderSignal(item.id.startsWith("current-") ? current : recorded, item, index);
  });
  if (!recorded.children.length) {
    renderSignal(recorded, { statement: "No recorded attempts.", evidence_ids: [] }, 0);
  }
  if (!current.children.length) {
    renderSignal(current, { statement: "No touched paths were recorded.", evidence_ids: [] }, 0);
  }

  const uncertaintyList = document.querySelector("#uncertainties");
  if (!brief.uncertainties.length) {
    uncertaintyList.append(element("li", "", "No unresolved evidence gaps."));
  }
  brief.uncertainties.forEach((item) => {
    uncertaintyList.append(element("li", "", item.statement));
  });

  const priority = { block: 4, unknown: 3, warn: 2, pass: 1 };
  const overall = brief.readiness.reduce(
    (worst, check) => priority[check.status] > priority[worst] ? check.status : worst,
    "pass"
  );
  const statusBox = document.querySelector("#overall-status");
  statusBox.dataset.status = overall;
  statusBox.querySelector(".status-code").textContent =
    { block: "NO", unknown: "?", warn: "!", pass: "GO" }[overall];
  statusBox.querySelector(".status-label").textContent =
    { block: "BLOCKED", unknown: "VERIFICATION UNKNOWN", warn: "REVIEW REQUIRED", pass: "READY TO CONTINUE" }[overall];

  const readinessGrid = document.querySelector("#readiness-grid");
  brief.readiness.forEach((check, index) => {
    const card = element("article", "readiness-card");
    card.dataset.status = check.status;
    const top = element("div", "readiness-top");
    top.append(
      element("span", "panel-index", String(index + 1).padStart(2, "0")),
      element("span", "status-chip", check.status.toUpperCase())
    );
    card.append(top, element("h3", "", check.label), element("p", "", check.detail));
    readinessGrid.append(card);
  });

  const actions = document.querySelector("#actions");
  brief.actions.forEach((action) => actions.append(element("li", "", action.instruction)));

  const evidenceGrid = document.querySelector("#evidence-grid");
  document.querySelector("#evidence-count").textContent = `${brief.evidence.length} SOURCES`;
  brief.evidence.forEach((item) => {
    const card = element("article", "evidence-card");
    card.id = item.id;
    const meta = element("div", "evidence-meta");
    meta.append(element("span", "", item.kind.toUpperCase()), element("span", "", item.locator));
    card.append(meta, element("h3", "", item.label));
    const digest = element("p", "digest", `SHA-256 / ${item.digest}`);
    digest.title = item.digest;
    card.append(digest);
    evidenceGrid.append(card);
  });
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: authHeaders, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || "Local evidence could not be loaded.");
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function candidateSignal(candidate) {
  if (candidate.unmatched_call_count) {
    const noun = candidate.unmatched_call_count === 1 ? "call" : "calls";
    return `${candidate.unmatched_call_count} unmatched ${noun}`;
  }
  return {
    completed: "Provider recorded completion",
    active: "Session may still be active",
    unknown: "Ending remains unknown",
    interrupted: "Interrupted signal recorded"
  }[candidate.ending];
}

function candidateStatus(candidate) {
  return candidate.unmatched_call_count ? "REVIEW" : candidate.ending.toUpperCase();
}

function formatUpdated(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

function renderCandidates() {
  const list = document.querySelector("#session-list");
  clear(list);
  const visible = state.candidates.filter((candidate) =>
    state.filter === "all" || candidate.ending === state.filter
  );
  document.querySelector("#session-empty").hidden = visible.length !== 0;
  visible.forEach((candidate) => {
    const row = element("article", "session-row");
    row.dataset.ending = candidate.ending;

    const provider = element("span", "provider-chip", candidate.provider.toUpperCase());
    const identity = element("div", "session-identity");
    const sessionName = element("strong", "", candidate.source_session_id);
    sessionName.translate = false;
    identity.append(
      sessionName,
      element("span", "session-meta", `${candidate.project_hint} · ${formatUpdated(candidate.updated_at)}`)
    );
    const signal = element("div", "session-signal");
    signal.append(
      element("strong", "", candidateSignal(candidate)),
      element("span", "session-meta", `${candidate.source_adapter.name}@${candidate.source_adapter.version}`)
    );
    const status = element("span", "status-chip", candidateStatus(candidate));
    const open = element("button", "open-session", "Open recovery");
    open.type = "button";
    open.dataset.candidateId = candidate.candidate_id;
    open.addEventListener("click", () => openCandidate(candidate.candidate_id, open, true));
    row.append(provider, identity, signal, status, open);
    list.append(row);
  });
}

function renderCatalog(catalog) {
  state.catalog = catalog;
  state.candidates = catalog.sessions;
  document.querySelector("#queue-count").textContent = String(catalog.sessions.length).padStart(2, "0");
  const reviewCount = catalog.sessions.filter((item) => item.unmatched_call_count > 0).length;
  document.querySelector("#queue-review-count").textContent = `${reviewCount} NEED REVIEW`;
  document.querySelector("#catalog-meta").textContent =
    `${catalog.repo_name} · ${catalog.sessions.length} bound · ${catalog.excluded_count} excluded`;
  renderCandidates();
}

function showInbox({ restoreFocus = true } = {}) {
  document.querySelector("#console-loading").hidden = true;
  document.querySelector("#brief-view").hidden = true;
  document.querySelector("#inbox-view").hidden = false;
  document.title = "Agent Ledger — Recovery Inbox";
  if (restoreFocus && state.selectedButton?.isConnected) state.selectedButton.focus();
}

function showBrief(brief, promptPayload, provider) {
  renderBrief(brief);
  state.continuationPrompt = promptPayload.prompt;
  document.querySelector("#copy-prompt").disabled = false;
  document.querySelector("#selected-provider").textContent = provider.toUpperCase();
  document.querySelector("#console-loading").hidden = true;
  document.querySelector("#inbox-view").hidden = true;
  document.querySelector("#brief-view").hidden = false;
  document.querySelector("#brief-title").focus({ preventScroll: true });
  document.title = `Agent Ledger — ${brief.session_id}`;
}

async function openCandidate(candidateId, trigger, pushHistory) {
  state.selectedButton = trigger || state.selectedButton;
  document.querySelector("#console-loading").hidden = false;
  document.querySelector("#inbox-view").hidden = true;
  const candidate = state.candidates.find((item) => item.candidate_id === candidateId);
  try {
    const [brief, promptPayload] = await Promise.all([
      fetchJson(`/api/sessions/${encodeURIComponent(candidateId)}/recovery`),
      fetchJson(`/api/sessions/${encodeURIComponent(candidateId)}/prompt`)
    ]);
    showBrief(brief, promptPayload, candidate?.provider || "session");
    if (pushHistory) {
      window.history.pushState({ view: "brief", candidateId }, "", `#session=${encodeURIComponent(candidateId)}`);
    }
  } catch (error) {
    showInbox({ restoreFocus: false });
    const status = document.querySelector("#console-status");
    status.textContent = `${error.message} Restart the local console if the source changed.`;
    status.focus();
  }
}

async function loadCompatibility() {
  state.mode = "compatibility";
  const [brief, promptPayload] = await Promise.all([
    fetchJson("/api/recovery"),
    fetchJson("/api/prompt")
  ]);
  document.querySelector(".brief-toolbar").hidden = true;
  showBrief(brief, promptPayload, brief.source_adapter.name);
  window.history.replaceState({ view: "compatibility" }, document.title, "/");
}

async function loadConsole() {
  const response = await fetch("/api/sessions", { headers: authHeaders, cache: "no-store" });
  if (response.status === 404) {
    await loadCompatibility();
    return;
  }
  if (!response.ok) throw new Error("The local recovery queue could not be loaded.");
  const catalog = await response.json();
  renderCatalog(catalog);
  showInbox({ restoreFocus: false });
  window.history.replaceState({ view: "inbox" }, document.title, "/");
}

function renderFatal(error, buttonLabel, action) {
  const main = document.querySelector("#main");
  const message = element("section", "fatal");
  const recovery = element("p", "", `${error.message} No repository changes were made.`);
  const retry = element("button", "copy-button", buttonLabel);
  retry.type = "button";
  retry.addEventListener("click", action);
  message.append(
    element("p", "kicker", "RECOVERY CONSOLE ERROR"),
    element("h2", "", "Local Evidence Unavailable"),
    recovery,
    retry
  );
  main.replaceChildren(message);
  retry.focus();
}

document.querySelector("#session-filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.filter = button.dataset.filter;
  document.querySelectorAll("button[data-filter]").forEach((item) => {
    item.setAttribute("aria-pressed", String(item === button));
  });
  renderCandidates();
});

document.querySelector("#back-to-inbox").addEventListener("click", () => {
  if (window.history.state?.view === "brief") window.history.back();
  else showInbox();
});

document.querySelector("#copy-prompt").addEventListener("click", async () => {
  const status = document.querySelector("#copy-status");
  try {
    await navigator.clipboard.writeText(state.continuationPrompt);
    status.textContent = "SAFE PROMPT COPIED";
  } catch {
    status.textContent = "COPY FAILED — CLIPBOARD PERMISSION DENIED";
  }
});

window.addEventListener("popstate", (event) => {
  if (event.state?.view === "brief" && event.state.candidateId) {
    openCandidate(event.state.candidateId, state.selectedButton, false);
  } else if (state.mode === "catalog") {
    showInbox();
  }
});

loadConsole().catch((error) => {
  renderFatal(error, "Reload Console", () => window.location.reload());
});
