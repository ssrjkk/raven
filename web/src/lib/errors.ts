/** Turns whatever a request rejected with into a line the console can show.

Every page used to type its handler parameter as `any` and read `.message` off it. That switched the
type checker off at exactly the place a failure becomes visible, so a rejection which is not an `Error`
— a bare string, a body FastAPI shaped as `{ "detail": ... }`, an `undefined` from a promise that
rejected with nothing — settled to `undefined`, the error state went empty, and the screen showed a
button that appeared to do nothing.
*/

const GENERIC = "Request failed";

/** Keys a rejection can carry its text under: `message` from an Error, `detail` from FastAPI. */
const MESSAGE_KEYS = ["message", "detail", "error"] as const;

export function errorMessage(value: unknown, fallback: string = GENERIC): string {
  return describe(value) ?? fallback;
}

function describe(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (value instanceof Error) return value.message.trim() || null;
  if (value === null || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  for (const key of MESSAGE_KEYS) {
    const field = record[key];
    if (typeof field === "string" && field.trim()) return field.trim();
  }
  return null;
}
