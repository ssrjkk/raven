import { Check, X } from "lucide-react";

/** The yes/no mark a row leads with, in the tone the status tokens set. */
export function StatusMark({ ok, size = 13 }: { ok: boolean; size?: number }) {
  const Mark = ok ? Check : X;
  return <Mark size={size} className={`flex-shrink-0 ${ok ? "text-success" : "text-danger"}`} />;
}
