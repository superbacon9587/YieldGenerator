export function periodCalculation(result, metric) {
  const rows = result.farm_totals ?? [];
  let values, unit, label;
  if (metric === "harvest") {
    values = result.years
      .map((year) => {
        const present = (result.yield_weight ?? []).flatMap((b) =>
          b.yearly
            .filter((r) => r.year === year && r.tons != null)
            .map((r) => r.tons),
        );
        return present.length ? present.reduce((a, b) => a + b, 0) : null;
      })
      .filter((v) => v != null);
    unit = "US short tons";
    label = "Sum of annual crop harvest totals";
  } else {
    const field =
      metric === "water"
        ? "water_applied_af"
        : metric === "relative"
          ? "relative_yield"
          : "profit";
    values = rows.map((r) => r[field]).filter((v) => v != null);
    unit =
      metric === "water"
        ? "acre-ft"
        : metric === "relative"
          ? "fraction of unstressed yield"
          : "USD";
    label =
      metric === "water"
        ? "Sum of yearly applied water"
        : metric === "relative"
          ? "Sum of yearly area-weighted relative yields"
          : "Sum of yearly modeled margins";
  }
  const sum = values.length ? values.reduce((a, b) => a + b, 0) : null;
  return {
    label,
    sum,
    count: values.length,
    average: sum == null ? null : sum / values.length,
    unit,
  };
}
