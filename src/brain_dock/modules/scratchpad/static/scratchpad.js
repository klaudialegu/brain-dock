// Scratchpad (ADR 0017): save the page while typing, a moment after the last key. It posts
// the same form the Save button does (with its CSRF token), so without scripts nothing is
// lost: Save still works. The text never goes anywhere but this app.
(() => {
  const form = document.querySelector("form[data-autosave]");
  if (!form) return;
  const state = form.querySelector("[data-save-state]");
  let timer = null;
  let last = form.elements.text.value;

  async function save() {
    timer = null;
    const text = form.elements.text.value;
    if (text === last) return;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "x-scratchpad-save": "1" },
        credentials: "same-origin",
      });
      if (response.status === 204) {
        last = text;
        if (state) state.textContent = "Saved";
      } else if (state) {
        state.textContent = "Not saved: use Save";
      }
    } catch {
      if (state) state.textContent = "Not saved: use Save";
    }
  }

  form.elements.text.addEventListener("input", () => {
    if (state) state.textContent = "";
    if (timer) clearTimeout(timer);
    timer = setTimeout(save, 800);
  });
  window.addEventListener("pagehide", () => {
    if (timer) save();
  });
})();
