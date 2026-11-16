// Presentation aggregation only: sums authoritative projections, never computes
// financial effects or modifies a balance. BigInt avoids Number precision loss.
export function sumMoney(values: string[]): string {
  let cents = 0n;
  for (const value of values) {
    if (!/^-?\d+(?:\.\d{1,2})?$/.test(value)) throw new Error("CBS ha devuelto un balance no válido.");
    const negative = value.startsWith("-");
    const [whole = "0", fraction = ""] = value.replace(/^-/, "").split(".");
    const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
    cents += negative ? -amount : amount;
  }
  const magnitude = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "-" : ""}${magnitude / 100n}.${String(magnitude % 100n).padStart(2, "0")}`;
}
