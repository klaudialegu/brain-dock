// The server renders the first values; this keeps them ticking without a reload.
(() => {
  const section = document.querySelector(".clocks");
  const referenceTz = section.dataset.referenceTz;
  const dateKey = (now, tz) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);

  function tick() {
    const now = new Date();
    const referenceDate = dateKey(now, referenceTz);
    for (const clock of section.querySelectorAll(".clock")) {
      const tz = clock.dataset.tz;
      clock.querySelector(".time").textContent =
        new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(now);
      clock.querySelector(".day").textContent =
        dateKey(now, tz) === referenceDate ? "" : new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" }).format(now);
    }
  }

  tick();
  setInterval(tick, 1000);
})();
