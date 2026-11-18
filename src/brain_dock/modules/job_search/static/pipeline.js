// Draws the pipeline Sankey from the JSON block the server rendered (no inline scripts: CSP).
(() => {
  const el = document.getElementById("pipeline-chart");
  const dataEl = document.getElementById("pipeline-data");
  if (!el || !dataEl || !window.echarts) return;

  const data = JSON.parse(dataEl.textContent);
  let chart;

  function render() {
    if (chart) chart.dispose();
    chart = window.echarts.init(el);
    chart.setOption({
      animation: false,
      // richText tooltips are drawn on the canvas, so no inline style attributes (CSP).
      tooltip: { trigger: "item", renderMode: "richText" },
      series: [
        {
          type: "sankey",
          nodeAlign: "left",
          left: 8,
          right: 110,
          emphasis: { focus: "adjacency" },
          data: data.nodes.map((n) => ({
            name: n.name,
            itemStyle: { color: n.color },
          })),
          links: data.links,
          lineStyle: { color: "gradient", opacity: 0.35 },
          label: { color: "#1D1B18", fontFamily: "Inter, system-ui, sans-serif" },
        },
      ],
    });
  }

  render();
  window.addEventListener("resize", () => chart && chart.resize());
})();
