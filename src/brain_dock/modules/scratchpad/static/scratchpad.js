// Scratchpad (ADR 0017): save the page while typing, a moment after the last key. It posts
// the same form the Save button does (with its CSRF token and the fingerprint of the text it
// loaded), so without scripts nothing changes: Save still works. Before any other form on the
// page is sent (pen, paper, size, new page), a pending save goes first, so the last words
// typed are never lost. The text never goes anywhere but this app.
(() => {
  const form = document.querySelector("form[data-autosave]");
  if (!form) return;
  const state = form.querySelector("[data-save-state]");
  let timer = null;
  let last = form.elements.text.value;
  let stale = false;
  let queue = Promise.resolve(); // one save at a time, so each carries the latest fingerprint

  const say = (text) => {
    if (state) state.textContent = text;
  };

  function save() {
    if (timer) clearTimeout(timer);
    timer = null;
    queue = queue.then(send);
    return queue;
  }

  async function send() {
    const text = form.elements.text.value;
    if (text === last || stale) return;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "x-scratchpad-save": "1" },
        credentials: "same-origin",
        keepalive: true, // finishes even if the page is closing
      });
      if (response.status === 204) {
        last = text;
        form.elements.base.value = response.headers.get("x-scratchpad-base") || "";
        say("Saved");
      } else if (response.status === 409) {
        stale = true; // never overwrite newer text: Save shows both sides
        say("This page changed elsewhere: use Save to see");
      } else {
        say("Not saved: use Save");
      }
    } catch {
      say("Not saved: use Save");
    }
  }

  form.elements.text.addEventListener("input", () => {
    say("");
    if (timer) clearTimeout(timer);
    timer = setTimeout(save, 800);
  });
  for (const other of document.querySelectorAll("form:not([data-autosave])")) {
    other.addEventListener("submit", async (event) => {
      if (form.elements.text.value === last || stale) return;
      event.preventDefault();
      await save();
      other.submit();
    });
  }
  window.addEventListener("pagehide", () => {
    if (form.elements.text.value !== last) save();
  });
})();
