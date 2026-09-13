import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth, jsonResponse } from "../lib/test-utils";
import LoginPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

beforeEach(() => {
  push.mockClear();
  vi.restoreAllMocks();
});

describe("LoginPage", () => {
  it("renders the e-shopping.com title and FAQ teaser tags", () => {
    renderWithAuth(<LoginPage />);
    expect(screen.getByText("e-shopping.com")).toBeInTheDocument();
    expect(screen.getByText("When will my order ship?")).toBeInTheDocument();
  });

  it("disables sign-in until an email is entered", () => {
    renderWithAuth(<LoginPage />);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled();
  });

  it("shows the not-found message when is_auth is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ email_addr: "x@x.com", is_auth: false, role: "customer", customer_context: null })
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

  it("redirects customers to /customer on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          email_addr: "cust@x.com",
          is_auth: true,
          role: "customer",
          customer_context: { customer_id: 1, title: "Ms.", first_name: "A", last_name: "B", email: "cust@x.com", latest_orders: [] },
        })
      )
    );
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "cust@x.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/customer"));
  });

  it("redirects CSRs to /csr on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ email_addr: "csr@x.com", is_auth: true, role: "csr", customer_context: null })
      )
    );
    renderWithAuth(<LoginPage />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "csr@x.com");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/csr"));
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
