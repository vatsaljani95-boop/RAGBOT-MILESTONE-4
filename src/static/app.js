const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const answerText = document.getElementById("answer-text");
const sourceEl = document.getElementById("source");
const updatedEl = document.getElementById("updated");
const stagesEl = document.getElementById("stages");

function setStatus(text, isError) {
  statusEl.hidden = !text;
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", Boolean(isError));
}

async function ask(question) {
  setStatus("Looking up published facts…");
  answerEl.hidden = true;
  const res = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const data = await res.json();
  if (!res.ok) {
    setStatus(data.detail || "Request failed", true);
    return;
  }
  setStatus("");
  answerText.textContent = data.text;
  sourceEl.replaceChildren();
  sourceEl.append("Source: ");
  if (data.source_url) {
    const link = document.createElement("a");
    link.href = data.source_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = data.source_url;
    sourceEl.append(link);
  } else {
    sourceEl.append("not applicable");
  }
  updatedEl.textContent = data.last_updated_from_sources
    ? `Last updated from sources: ${data.last_updated_from_sources}`
    : "Last updated from sources: —";
  answerEl.hidden = false;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) {
    setStatus("Please ask a factual question.", true);
    return;
  }
  ask(question).catch((err) => setStatus(String(err), true));
});

document.querySelectorAll(".examples button").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.q;
    ask(button.dataset.q).catch((err) => setStatus(String(err), true));
  });
});

async function loadStages() {
  const res = await fetch("/stages");
  const data = await res.json();
  stagesEl.textContent = JSON.stringify(data, null, 2);
}

document.querySelector(".stages").addEventListener("toggle", (event) => {
  if (event.target.open) loadStages();
});
