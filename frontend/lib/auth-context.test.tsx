import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithAuth, jsonResponse } from "./test-utils";
import { isSessionRejection } from "./auth-context";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
}));

const session = { email_addr: "c@x.com", role: "customer" as const, customer_context: null };

function Caller({ call }: { call: () => Promise<Response> }) {
  return <button onClick={() => call()}>call</button>;
}

const post = (url: string) => () => fetch(url, { method: "POST" });

beforeEach(() => {
  replace.mockClear();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("isSessionRejection", () => {
  it("flags 401/403 on API calls but not on /auth or other statuses", () => {
    expect(isSessionRejection("/api/support/general", 401)).toBe(true);
    expect(isSessionRejection("/api/approval/start", 403)).toBe(true);
    expect(isSessionRejection("/api/auth", 401)).toBe(false);
    expect(isSessionRejection("/api/support/general", 500)).toBe(false);
    expect(isSessionRejection("/other", 401)).toBe(false);
    expect(isSessionRejection("/api/auth/logout", 401)).toBe(false);
    // absolute NEXT_PUBLIC_API_URL style
    expect(isSessionRejection("http://localhost:8000/api/support/general", 403)).toBe(true);
    expect(isSessionRejection("http://localhost:8000/api/auth", 401)).toBe(false);
  });
});

describe("AuthProvider 401/403 handler", () => {
  for (const status of [401, 403]) {
    it(`clears the stored session and returns to login on ${status}`, async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ...jsonResponse({}, false), status }));
      renderWithAuth(<Caller call={post("/api/support/general")} />, { seedSession: session });
      await waitFor(() => expect(localStorage.getItem("csa_session")).not.toBeNull());
      screen.getByRole("button", { name: "call" }).click();
      await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
      expect(localStorage.getItem("csa_session")).toBeNull();
    });
  }

  it("handles URL and Request inputs, not just strings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ...jsonResponse({}, false), status: 401 }));
    renderWithAuth(
      <Caller call={() => fetch(new Request("http://localhost/api/support/general", { method: "POST" }))} />,
      { seedSession: session }
    );
    screen.getByRole("button", { name: "call" }).click();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("does not redirect when /api/auth itself returns 401 (failed login)", async () => {
    const mock = vi.fn().mockResolvedValue({ ...jsonResponse({}, false), status: 401 });
    vi.stubGlobal("fetch", mock);
    renderWithAuth(<Caller call={post("/api/auth")} />, { seedSession: session });
    screen.getByRole("button", { name: "call" }).click();
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(1));
    expect(replace).not.toHaveBeenCalled();
    expect(localStorage.getItem("csa_session")).not.toBeNull();
  });

  it("leaves the session alone on a normal 500", async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({}, false));
    vi.stubGlobal("fetch", mock);
    renderWithAuth(<Caller call={post("/api/support/general")} />, { seedSession: session });
    screen.getByRole("button", { name: "call" }).click();
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(1));
    expect(replace).not.toHaveBeenCalled();
    expect(localStorage.getItem("csa_session")).not.toBeNull();
  });
});
