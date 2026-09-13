import { render } from "@testing-library/react";
import { AuthProvider, AuthSession } from "./auth-context";

const STORAGE_KEY = "csa_session";

// Seeds localStorage with a session *before* mounting, so AuthProvider's
// hydration effect picks it up — mirrors how a real page load restores state.
export function renderWithAuth(
  ui: React.ReactElement,
  { seedSession }: { seedSession?: AuthSession } = {}
) {
  if (seedSession) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(seedSession));
  }
  return render(<AuthProvider>{ui}</AuthProvider>);
}

export function jsonResponse(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: async () => body } as Response;
}
