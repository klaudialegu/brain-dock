// Scratchpad (ADR 0017): save the page while typing, a moment after the last key. It posts
// the same form the Save button does (with its CSRF token and the fingerprint of the text it
// loaded), so without scripts nothing changes: Save still works.
// Typed text is never dropped: a pending save goes before any other form on the page (pen,
// paper, size, new page); if the save is refused, that form waits and the page says why,
// and leaving asks first. The text never goes anywhere but this app.
(() => {
  const form = document.querySelector("form[data-autosave]");
  if (!form) return;
  const box = form.elements.text;
  const state = form.querySelector("[data-save-state]");
  // A page shown after a refused save holds text that isn't saved yet.
  let last = form.hasAttribute("data-unsaved") ? null : box.value;
  let refused = form.hasAttribute("data-unsaved");
  let stale = false; // changed elsewhere: only the Save button (which merges) may go on
  let timer = null;
  let queue = Promise.resolve(); // one save at a time, so each carries the latest fingerprint

  const say = (text) => {
    if (state) state.textContent = text;
  };
  const unsaved = () => box.value !== last;

  function save() {
    if (timer) clearTimeout(timer);
    timer = null;
    queue = queue.then(send);
    return queue;
  }

  async function send() {
    const text = box.value;
    if (text === last) return true;
    if (stale || form.dataset.posting) return false;
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
        refused = false;
        form.elements.base.value = response.headers.get("x-scratchpad-base") || "";
        say(box.value === text ? "Saved" : "");
        return true;
      }
      if (response.status === 409) {
        stale = true;
        say("This page changed elsewhere. Select Save to bring the new lines in.");
      } else if (response.status === 410) {
        stale = true; // removed in another tab: Save shows what was typed, with Undo
        say("This page was removed. Select Save to keep what you typed.");
      } else {
        say("Not saved: select Save to see why.");
      }
    } catch {
      say("Not saved: select Save to try again.");
    }
    refused = true;
    return false;
  }

  box.addEventListener("input", () => {
    if (!stale) say("");
    if (timer) clearTimeout(timer);
    timer = setTimeout(save, 800);
  });
  form.addEventListener("submit", async (event) => {
    // Save: finish through the same queue as autosave, so two saves never race. Saved:
    // nothing more to send. Refused (changed or removed elsewhere): post the form, and the
    // page that comes back says why and keeps what was typed.
    if (form.dataset.posting) return;
    event.preventDefault();
    if (await save()) {
      if (form.hasAttribute("data-unsaved")) {
        location.assign(form.action.replace(/\/text$/, "")); // the page, without the notice
      } else {
        say("Saved");
      }
    } else {
      form.dataset.posting = "1";
      form.submit();
    }
  });
  for (const other of document.querySelectorAll("form:not([data-autosave])")) {
    other.addEventListener("submit", async (event) => {
      if (!unsaved()) return;
      event.preventDefault();
      if (await save()) other.submit(); // the words first, then the change
    });
  }
  window.addEventListener("beforeunload", (event) => {
    if (unsaved() && (stale || refused)) event.preventDefault(); // ask before dropping text
  });
  window.addEventListener("pagehide", () => {
    if (unsaved()) save();
  });
})();
