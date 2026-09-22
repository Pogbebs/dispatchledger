/** Display helpers. Money and quantities come from the API as strings,
 *  deliberately: they are NUMERIC in Postgres and turning them into
 *  JavaScript numbers would reintroduce the float rounding the schema avoids.
 *  Only formatting converts, never arithmetic. */

export function money(value: string): string {
  return `$${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function price(value: string): string {
  return `$${Number(value).toFixed(4)}`;
}

export function gallons(value: string | null): string {
  if (value === null) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function day(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function dayTime(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function Pill({ status }: { status: string }) {
  return (
    <span className={`pill pill-${status}`}>{status.replace("_", " ")}</span>
  );
}
