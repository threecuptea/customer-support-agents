import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth, jsonResponse } from "../lib/test-utils";
import LoginPage from "./page";
import authFixtures from "../lib/fixtures/auth-responses.json";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

beforeEach(() => {
  localStorage.clear();
  push.mockClear();
  vi.restoreAllMocks();
});

describe("LoginPage", () => {
  it("renders the e-shopping.com title and FAQ teaser tags", () => {
    renderWithAuth(<LoginPage />);
    expect(screen.getByText("e-shopping.com")).toBeInTheDocument();
    expect(screen.getByText("When will my order ship?")).toBeInTheDocument();
  });

  it("keeps sign-in enabled so autofilled emails (no onChange) still work", () => {
    renderWithAuth(<LoginPage />);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
  });

  it("tells the customer instead of failing silently when the email reads as empty", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithAuth(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(screen.getByText(/please type your email address/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("signs in with a DOM-set email value that never fired onChange", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ email_addr: "x@x.com", is_auth: false, role: "customer" }, null])
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithAuth(<LoginPage />);
    // Simulate autofill: set the DOM value directly, without dispatching an input event.
    (screen.getByPlaceholderText("you@example.com") as HTMLInputElement).value = "x@x.com";
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ email_addr: "x@x.com" });
  });

  it("shows the not-found message when is_auth is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse([{ email_addr: "x@x.com", is_auth: false, role: "customer" }, null])
      )
    );
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x@x.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(
      await screen.findByText(/unable to find any customer with the login email/i)
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("redirects customers to /customer and stores the CustomerContext (2nd array element)", async () => {
    // Fixture is generated from the backend models (scripts/export_auth_fixture.py), so a
    // backend contract change breaks this test instead of silently passing on a stale mock.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(authFixtures.customer)));
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "customer@example.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/customer"));
    const stored = JSON.parse(localStorage.getItem("csa_session")!);
    expect(stored.role).toBe("customer");
    expect(stored.email_addr).toBe("customer@example.com");
    expect(stored.customer_context).toEqual(authFixtures.customer[1]);
  });

  it("redirects CSRs to /csr on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(authFixtures.csr)
      )
    );
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "csr@x.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/csr"));
    expect(JSON.parse(localStorage.getItem("csa_session")!).customer_context).toBeNull();
  });

  it("shows a generic error banner on network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x@x.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/could not reach the server/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
