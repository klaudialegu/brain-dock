// Focus mode (ADR 0016): a dot-ring timer, one dot per minute. Elapsed minutes fade, the
// current one glows in the highlighter of the day. Time comes from the clock, not from
// counting ticks, so a background tab stays accurate. Reduced motion: the ring still
// updates, without transitions (CSS). "Park a thought" posts to the capture path and
// stays on the page; without scripts it posts normally.
(() => {
  const timer = document.querySelector("[data-focus]");
  if (timer) {
    const total = Number(timer.dataset.minutes) * 60;
    const dots = [...timer.querySelectorAll("circle")];
    const clock = timer.querySelector("[data-clock]");
    const state = timer.querySelector("[data-state]");
    const toggle = document.querySelector("[data-toggle]");
    let spent = 0; // seconds done before the current run
    let since = Date.now();
    let running = true;
    let ticker = null;

    const elapsed = () => Math.min(total, spent + (running ? (Date.now() - since) / 1000 : 0));

    function draw() {
      const seconds = elapsed();
      const minute = Math.floor(seconds / 60);
      dots.forEach((dot, i) => {
        dot.classList.toggle("is-past", i < minute);
        dot.classList.toggle("is-now", i === minute && seconds < total);
      });
      const left = Math.ceil(total - seconds);
      clock.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      timer.dataset.elapsedMinutes = String(minute);
      if (seconds >= total) {
        stop();
        state.textContent = "Time's up";
        toggle.hidden = true;
      }
    }

    function stop() {
      if (ticker) clearInterval(ticker);
      ticker = null;
    }

    function start() {
      since = Date.now();
      running = true;
      ticker = setInterval(draw, 1000);
      draw();
    }

    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      if (running) {
        spent = elapsed();
        running = false;
        stop();
        toggle.textContent = "Resume";
        state.textContent = "Paused";
        timer.dataset.paused = "true";
        draw();
      } else {
        toggle.textContent = "Pause";
        state.textContent = `${timer.dataset.minutes} min`;
        timer.dataset.paused = "false";
        start();
      }
    });
    start();
  }

  const park = document.querySelector("form[data-park]");
  if (park) {
    const said = park.querySelector("[data-park-state]");
    park.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!park.elements.text.value.trim()) return;
      try {
        const response = await fetch(park.action, {
          method: "POST",
          body: new FormData(park),
          headers: { "x-scratchpad-capture": "1" },
          credentials: "same-origin",
        });
        if (response.status === 204) {
          park.elements.text.value = "";
          said.textContent = "Parked.";
          return;
        }
      } catch {
        // fall through: post the form the plain way, so the thought isn't lost
      }
      park.submit();
    });
  }
})();
