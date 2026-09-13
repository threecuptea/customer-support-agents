import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth, jsonResponse } from "../../lib/test-utils";
import CsrPage from "./page";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const csrSession = { email_addr: "csr@x.com", role: "csr" as const, customer_context: null };

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  vi.restoreAllMocks();
});

describe("CsrPage", () => {
  it("redirects to / when there is no csr session", async () => {
    renderWithAuth(<CsrPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("does not render the draft form for a customer session", async () => {
    renderWithAuth(<CsrPage />, {
      seedSession: { email_addr: "cust@x.com", role: "customer", customer_context: null },
    });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText(/draft & approve customer letters/i)).not.toBeInTheDocument();
  });

  it("drafts and approves a letter for a csr session", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          requires_input: true,
          draft: "Dear customer, ...",
          status: "awaiting_review",
          final_output: "",
          revision_count: 0,
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          requires_input: false,
          draft: "Dear customer, ...",
          status: "sent",
          final_output: "Dear customer, ...",
          revision_count: 0,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<CsrPage />, { seedSession: csrSession });
    await screen.findByText(/draft & approve customer letters/i);

    await userEvent.type(
      screen.getByPlaceholderText(/friendly email apologizing/i),
      "Apologize for a shipping delay"
    );
    await userEvent.click(screen.getByRole("button", { name: /draft it/i }));

    expect(await screen.findByText("Dear customer, ...")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /approve & send/i }));

    expect(await screen.findByText(/approved & sent/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("logs out and returns to / from the header button", async () => {
    renderWithAuth(<CsrPage />, { seedSession: csrSession });
    await screen.findByText(/draft & approve customer letters/i);
    await userEvent.click(screen.getByRole("button", { name: /log out/i }));
    expect(push).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("csa_session")).toBeNull();
  });
});
