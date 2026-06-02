export type FormAutofillKind = "shared" | "attorney";

function sessionKey(caseId: string, kind: FormAutofillKind): string {
  return `form-autofill:${caseId}:${kind}`;
}

export function saveFormAutofillSession(
  caseId: string,
  kind: FormAutofillKind,
  jobId: string
): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(sessionKey(caseId, kind), jobId);
}

export function readFormAutofillSession(
  caseId: string,
  kind: FormAutofillKind
): string | null {
  if (typeof window === "undefined") return null;

  const raw = window.sessionStorage.getItem(sessionKey(caseId, kind));
  if (!raw || typeof raw !== "string") return null;
  return raw;
}

export function clearFormAutofillSession(caseId: string, kind: FormAutofillKind): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(sessionKey(caseId, kind));
}
