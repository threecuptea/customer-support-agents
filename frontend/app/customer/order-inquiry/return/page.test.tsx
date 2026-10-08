import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithOrderInquiry, jsonResponse } from "../../../../lib/test-utils";
import { Order } from "../../../../lib/auth-context";
import ExchangeReturnPage from "./page";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const deliveredOrder: Order = {
  order_id: 2001,
  order_date: "2026-07-01T00:00:00Z",
  total_amount_incl_tax: 110,
  tax_applied_rate: 0.08,
  status: "delivered",
  notes: null,
  ship_date: "2026-07-02T00:00:00Z",
  estimated_delivery_date: "2026-07-05T00:00:00Z",
  tracking_number: "1Z-A",
  delivery_date: "2026-07-05T00:00:00Z",
  items: [
    {
      product_id: "P1",
      product_name: "Bike Light",
      supplier_name: "Premier Merchandize",
      unit_price: 30.26,
      number_units: 2,
      nonrefundable_item: false,
      nonrefundable_reason: null,
    },
    {
      product_id: "P2",
      product_name: "Silk Bra",
      supplier_name: "Acme",
      unit_price: 40,
      number_units: 1,
      nonrefundable_item: true,
      nonrefundable_reason: "intimate item",
    },
  ],
};

const unshippedOrder: Order = { ...deliveredOrder, status: "pending", delivery_date: null };

function sessionWith(order: Order) {
  return {
    email_addr: "sonya@x.com",
    role: "customer" as const,
    customer_context: {
      customer_id: 1,
      title: "Ms." as const,
      first_name: "Sonya",
      last_name: "Ling",
      email: "sonya@x.com",
      latest_orders: [order],
    },
  };
}

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  vi.restoreAllMocks();
});

async function goToItemizeStep(reasonLabelRegex: RegExp = /wrong size or fit/i) {
  const fetchMock = vi.fn().mockResolvedValueOnce(
    jsonResponse({ thread_id: "t1", response: "We recommend 'Return'." })
  );
  vi.stubGlobal("fetch", fetchMock);

  renderWithOrderInquiry(<ExchangeReturnPage />, {
    seedSession: sessionWith(deliveredOrder),
    seedOrderInquiry: { threadId: "t1", targetOrder: deliveredOrder },
  });

  await userEvent.click(screen.getByRole("radio", { name: reasonLabelRegex }));
  await userEvent.click(screen.getByRole("button", { name: /submit the survey/i }));
  await screen.findByText("We recommend 'Return'.");
  await userEvent.click(screen.getByRole("button", { name: /start return for refund process/i }));

  await userEvent.click(screen.getByRole("checkbox", { name: /confirm that i have read/i }));
  await userEvent.click(screen.getByRole("button", { name: /acknowledge & proceed/i }));
  await screen.findByText(/return\/ refund for order #2001/i);

  return fetchMock;
}

describe("ExchangeReturnPage", () => {
  it("redirects to order-inquiry when there's no target order in context", async () => {
    renderWithOrderInquiry(<ExchangeReturnPage />, { seedSession: sessionWith(deliveredOrder) });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/customer/order-inquiry"));
  });

  it("redirects to order-inquiry when the order hasn't been delivered yet", async () => {
    renderWithOrderInquiry(<ExchangeReturnPage />, {
      seedSession: sessionWith(unshippedOrder),
      seedOrderInquiry: { threadId: "t1", targetOrder: unshippedOrder },
    });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/customer/order-inquiry"));
  });

  it("submits the survey, shows the recommendation, and gates the bypass button", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ thread_id: "t1", response: "We recommend 'exchange'." })
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithOrderInquiry(<ExchangeReturnPage />, {
      seedSession: sessionWith(deliveredOrder),
      seedOrderInquiry: { threadId: "t1", targetOrder: deliveredOrder },
    });

    const bypassButton = screen.getByRole("button", { name: /start return for refund process/i });
    const submitButton = screen.getByRole("button", { name: /submit the survey/i });
    expect(bypassButton).toBeDisabled();
    expect(submitButton).toBeDisabled(); // no reason selected yet

    await userEvent.click(screen.getByRole("radio", { name: /wrong size or fit/i }));
    await userEvent.click(submitButton);

    expect(await screen.findByText("We recommend 'exchange'.")).toBeInTheDocument();
    expect(bypassButton).not.toBeDisabled();
    expect(submitButton).toBeDisabled(); // grayed out once submitted

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.thread_id).toBe("t1");
    expect(body.reason_option).toBe(
      "Size is too small or too large, different from size chart or just does not fit well"
    );
    expect(body.reason_input).toBeNull();
  });

  it("hides the normal return/refund button for special exchange handling", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({ thread_id: "t1", response: "We will expedite.", special_exchange_handling: true })
      )
    );
    renderWithOrderInquiry(<ExchangeReturnPage />, {
      seedSession: sessionWith(deliveredOrder),
      seedOrderInquiry: { threadId: "t1", targetOrder: deliveredOrder },
    });
    await userEvent.click(screen.getByRole("radio", { name: /damaged|defective/i }));
    await userEvent.click(screen.getByRole("button", { name: /submit the survey/i }));

    expect(await screen.findByText("We will expedite.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start return for refund process/i })).not.toBeInTheDocument();
  });

  it("requires the explanation box when 'Others' is picked", async () => {
    renderWithOrderInquiry(<ExchangeReturnPage />, {
      seedSession: sessionWith(deliveredOrder),
      seedOrderInquiry: { threadId: "t1", targetOrder: deliveredOrder },
    });

    await userEvent.click(screen.getByRole("radio", { name: /^others$/i }));
    expect(screen.getByRole("button", { name: /submit the survey/i })).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText(/describe your reason/i), "It's a long story");
    expect(screen.getByRole("button", { name: /submit the survey/i })).not.toBeDisabled();
  });

  it("requires acknowledging the policy checkbox before proceeding", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ thread_id: "t1", response: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithOrderInquiry(<ExchangeReturnPage />, {
      seedSession: sessionWith(deliveredOrder),
      seedOrderInquiry: { threadId: "t1", targetOrder: deliveredOrder },
    });
    await userEvent.click(screen.getByRole("radio", { name: /wrong size or fit/i }));
    await userEvent.click(screen.getByRole("button", { name: /submit the survey/i }));
    await screen.findByText("ok");
    await userEvent.click(screen.getByRole("button", { name: /start return for refund process/i }));

    expect(screen.getByText(/scroll down and read the full return policy/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /acknowledge & proceed/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /confirm that i have read/i }));
    expect(screen.getByRole("button", { name: /acknowledge & proceed/i })).not.toBeDisabled();
  });

  it("submits the itemized return and shows the decision, greying out the table", async () => {
    const fetchMock = await goToItemizeStep();

    const refundRequest = {
      refund_request_id: 0,
      request_date: "2026-08-01T00:00:00Z",
      status: "auto_approve",
      requires_manual_approval: false,
      requires_manual_approval_reason: null,
      notes_for_human_review_override: null,
      decided_by: null,
      decision_reason: null,
      decided_date: null,
      returned_order: {
        origin_order_id: 2001,
        original_delivery_date: "2026-07-05T00:00:00Z",
        returned_date: null,
        status: "pending",
        tax_applied_rate: 0.08,
        estimated_amount_refund_incl_tax: 65.36,
        refurbished_amount_incl_tax: 0,
        processed_date: null,
      },
    };
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "Congratulations!! It's in my authority to approve your request.",
        initial_return_refund_decision: {
          order_refund_status: "The return/ refund request has been approved by an automatic agent.",
        },
        refund_request_to_process: refundRequest,
      })
    );

    await userEvent.click(screen.getAllByRole("checkbox")[0]); // select the Bike Light row
    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));

    expect(
      await screen.findByText("The return/ refund request has been approved by an automatic agent.")
    ).toBeInTheDocument();
    expect(screen.getByText(/65\.36/)).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")[0]).toBeDisabled();

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body).toEqual({ thread_id: "t1", items: [{ product_id: "P1", qty: 2 }] });
  });

  it("requires at least one selected item before submitting", async () => {
    const fetchMock = await goToItemizeStep();
    fetchMock.mockClear();

    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));
    expect(await screen.findByText(/select at least one item/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("processes the request and swaps the action buttons to Exit/Back to order details", async () => {
    const fetchMock = await goToItemizeStep();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "ok to proceed",
        initial_return_refund_decision: {
          order_refund_status: "The return/ refund request has been approved by an automatic agent.",
        },
        refund_request_to_process: {
          refund_request_id: 0,
          request_date: "2026-08-01T00:00:00Z",
          status: "auto_approve",
          requires_manual_approval: false,
          requires_manual_approval_reason: null,
          notes_for_human_review_override: null,
          decided_by: null,
          decision_reason: null,
          decided_date: null,
          returned_order: {
            origin_order_id: 2001,
            original_delivery_date: "2026-07-05T00:00:00Z",
            returned_date: null,
            status: "pending",
            tax_applied_rate: 0.08,
            estimated_amount_refund_incl_tax: 65.36,
            refurbished_amount_incl_tax: 0,
            processed_date: null,
          },
        },
      })
    );
    await userEvent.click(screen.getAllByRole("checkbox")[0]);
    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));
    await screen.findByText("ok to proceed");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "You would receive a confirmation email.",
        assigned_refund_request_id: 7,
        refund_request_to_process: {
          refund_request_id: 7,
          request_date: "2026-08-01T00:00:00Z",
          status: "auto_approve",
          requires_manual_approval: false,
          requires_manual_approval_reason: null,
          notes_for_human_review_override: null,
          decided_by: "Agent",
          decision_reason: null,
          decided_date: "2026-08-01T00:00:00Z",
          returned_order: {
            origin_order_id: 2001,
            original_delivery_date: "2026-07-05T00:00:00Z",
            returned_date: null,
            status: "pending",
            tax_applied_rate: 0.08,
            estimated_amount_refund_incl_tax: 65.36,
            refurbished_amount_incl_tax: 0,
            processed_date: null,
          },
        },
      })
    );
    await userEvent.click(screen.getByRole("button", { name: /process the request/i }));

    expect(await screen.findByText("You would receive a confirmation email.")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /process the request/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^cancel$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back to order details/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /exit/i }).length).toBeGreaterThan(0);

    // Processing does not take chat away: the button is still there and still opens chat.
    const chatButton = screen.getByRole("button", { name: /i like to chat/i });
    expect(chatButton).toBeEnabled();
    await userEvent.click(chatButton);
    expect(screen.getByPlaceholderText(/can a human review/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /i like to chat/i })).toBeDisabled();
  });

  it("lets the customer chat, and shows the human-review notes box once offered", async () => {
    const fetchMock = await goToItemizeStep();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "rejected",
        initial_return_refund_decision: {
          order_refund_status:
            "The return/ refund request has been rejected by an automatic agent because it has passed the return window deadline",
        },
        refund_request_to_process: {
          refund_request_id: 0,
          request_date: "2026-08-01T00:00:00Z",
          status: "pending",
          requires_manual_approval: false,
          requires_manual_approval_reason: null,
          notes_for_human_review_override: null,
          decided_by: null,
          decision_reason: null,
          decided_date: null,
          returned_order: {
            origin_order_id: 2001,
            original_delivery_date: "2026-07-05T00:00:00Z",
            returned_date: null,
            status: "pending",
            tax_applied_rate: 0.08,
            estimated_amount_refund_incl_tax: 60.52,
            refurbished_amount_incl_tax: 0,
            processed_date: null,
          },
        },
      })
    );
    await userEvent.click(screen.getAllByRole("checkbox")[0]);
    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));
    await screen.findByText("rejected");

    await userEvent.click(screen.getByRole("button", { name: /i like to chat/i }));
    expect(screen.getByRole("button", { name: /i like to chat/i })).toBeDisabled();

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "I can offer a human review.",
        request_human_review_return_refund: true,
      })
    );
    await userEvent.type(
      screen.getByPlaceholderText(/can a human review/i),
      "I really think this should be approved"
    );
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("I can offer a human review.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/never wore the item/i)).toBeInTheDocument();

    const chatBody = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(chatBody).toEqual({ thread_id: "t1", user_conversation: "I really think this should be approved" });
  });

  it("resets itemize input without calling the backend", async () => {
    const fetchMock = await goToItemizeStep();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        response: "ok",
        initial_return_refund_decision: { order_refund_status: "The return/ refund request ..." },
        refund_request_to_process: null,
      })
    );
    await userEvent.click(screen.getAllByRole("checkbox")[0]);
    await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));
    await screen.findByText("ok");

    expect(screen.getByRole("button", { name: /process the request/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /i like to chat/i })).toBeDisabled();

    fetchMock.mockClear();
    await userEvent.click(screen.getByRole("button", { name: /reset input/i }));

    expect(screen.queryByText("ok")).not.toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")[0]).not.toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
