"use strict";

const token = document.querySelector('meta[name="agent-ledger-token"]').content;
const authHeaders = { "X-Agent-Ledger-Token": token };
let continuationPrompt = "";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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
  const trace = element("div", "evidence-link", evidenceText(item.evidence_ids));
  row.append(trace);
  target.append(row);
}

function renderBrief(brief) {
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
    const target = item.id.startsWith("current-") ? current : recorded;
    renderSignal(target, item, index);
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

async function loadConsole() {
  const [briefResponse, promptResponse] = await Promise.all([
    fetch("/api/recovery", { headers: authHeaders, cache: "no-store" }),
    fetch("/api/prompt", { headers: authHeaders, cache: "no-store" })
  ]);
  if (!briefResponse.ok || !promptResponse.ok) throw new Error("Local evidence could not be loaded.");
  const brief = await briefResponse.json();
  const promptPayload = await promptResponse.json();
  continuationPrompt = promptPayload.prompt;
  renderBrief(brief);
  document.querySelector("#copy-prompt").disabled = false;
  window.history.replaceState({}, document.title, "/");
}

document.querySelector("#copy-prompt").addEventListener("click", async () => {
  const status = document.querySelector("#copy-status");
  try {
    await navigator.clipboard.writeText(continuationPrompt);
    status.textContent = "SAFE PROMPT COPIED";
  } catch {
    status.textContent = "COPY FAILED — CLIPBOARD PERMISSION DENIED";
  }
});

loadConsole().catch((error) => {
  const main = document.querySelector("#main");
  const message = element("section", "fatal");
  const recovery = element("p", "", `${error.message} Reload the capability URL or restart the local demo.`);
  const retry = element("button", "copy-button", "Reload Console");
  retry.type = "button";
  retry.addEventListener("click", () => window.location.reload());
  message.append(element("p", "kicker", "RECOVERY CONSOLE ERROR"), element("h2", "", "Local Evidence Unavailable"), recovery, retry);
  main.replaceChildren(message);
});
