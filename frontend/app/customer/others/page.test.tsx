import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth, jsonResponse } from "../../../lib/test-utils";
import GeneralInquiryPage from "./page";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const customerSession = {
  email_addr: "cust@x.com",
  role: "customer" as const,
  customer_context: {
    customer_id: 1,
    title: "Ms." as const,
    first_name: "Ada",
    last_name: "Lovelace",
    email: "cust@x.com",
    latest_orders: [],
  },
};

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  vi.restoreAllMocks();
});

describe("GeneralInquiryPage", () => {
  it("redirects to / when there is no customer session", async () => {
    renderWithAuth(<GeneralInquiryPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("greets the customer and starts with 'Request an answer'", async () => {
    renderWithAuth(<GeneralInquiryPage />, { seedSession: customerSession });
    expect(await screen.findByText(/hi ms\. lovelace/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /request an answer/i })).toBeInTheDocument();
  });

  it("asks a question, shows the answer, and reuses thread_id on a follow-up", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          general_inquiry: "What is your return policy?",
          response: "We accept returns within 35 days of delivery for unused items",
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          general_inquiry: "How long does delivery take?",
          response: "Standard shipping takes 3 to 5 business days.",
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<GeneralInquiryPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);

    const input = screen.getByPlaceholderText(/return policy/i);
    await userEvent.type(input, "What is your return policy?");
    await userEvent.click(screen.getByRole("button", { name: /request an answer/i }));

    expect(
      await screen.findByText("We accept returns within 35 days of delivery for unused items")
    ).toBeInTheDocument();
    expect(screen.getByText("What is your return policy?")).toBeInTheDocument();

    const askAgainButton = screen.getByRole("button", { name: /ask another question/i });
    await userEvent.type(input, "How long does delivery take?");
    await userEvent.click(askAgainButton);

    expect(await screen.findByText("Standard shipping takes 3 to 5 business days.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondCallBody.thread_id).toBe("t1");
  });

  it("navigates to order inquiry", async () => {
    renderWithAuth(<GeneralInquiryPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);
    await userEvent.click(screen.getByRole("button", { name: /go to order inquiry/i }));
    expect(push).toHaveBeenCalledWith("/customer/order-inquiry");
  });

  it("clears the session and returns home on Exit", async () => {
    renderWithAuth(<GeneralInquiryPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);
    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);
    expect(push).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("csa_session")).toBeNull();
  });
});
