import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithOrderInquiry, jsonResponse } from "../../../lib/test-utils";
import { Order } from "../../../lib/auth-context";
import OrderInquiryPage from "./page";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const orderOlder: Order = {
  order_id: 1001,
  order_date: "2026-07-01T00:00:00Z",
  total_amount_incl_tax: 50,
  tax_applied_rate: 0.08,
  status: "delivered",
  notes: null,
  ship_date: "2026-07-02T00:00:00Z",
  estimated_delivery_date: "2026-07-05T00:00:00Z",
  tracking_number: "1Z-OLD",
  delivery_date: "2026-07-05T00:00:00Z",
  items: [
    {
      product_id: "P1",
      product_name: "Widget",
      supplier_name: "Acme",
      unit_price: 25,
      number_units: 2,
      nonrefundable_item: false,
      nonrefundable_reason: null,
    },
  ],
};

const orderNewer: Order = {
  order_id: 1002,
  order_date: "2026-08-01T00:00:00Z",
  total_amount_incl_tax: 30,
  tax_applied_rate: 0.08,
  status: "transit",
  notes: null,
  ship_date: "2026-08-02T00:00:00Z",
  estimated_delivery_date: "2026-08-10T00:00:00Z",
  tracking_number: "1Z-NEW",
  delivery_date: null,
  items: [
    {
      product_id: "P2",
      product_name: "Gadget",
      supplier_name: "Beta",
      unit_price: 30,
      number_units: 1,
      nonrefundable_item: false,
      nonrefundable_reason: null,
    },
  ],
};

function sessionWith(orders: Order[]) {
  return {
    email_addr: "sonya@x.com",
    role: "customer" as const,
    customer_context: {
      customer_id: 1,
      title: "Ms." as const,
      first_name: "Sonya",
      last_name: "Ling",
      email: "sonya@x.com",
      latest_orders: orders,
    },
  };
}

// /order/init is followed by GET /return_refund/by_order/{id} (CSA-23: the order's refund request card). Answer that
// one here (default: the order has no request) and leave every other call to the test's own queued mock, so
// the existing sequence/index assertions are unaffected.
function stubFetch(fetchMock: ReturnType<typeof vi.fn>, byOrder: unknown = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) =>
      String(url).includes("/return_refund/by_order/") ? Promise.resolve(jsonResponse(byOrder)) : fetchMock(url, init)
    )
  );
}

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  vi.restoreAllMocks();
});

describe("OrderInquiryPage", () => {
  it("redirects to / when there is no customer session", async () => {
    renderWithOrderInquiry(<OrderInquiryPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("lists orders sorted descending by order_date, with customer name and email", async () => {
    renderWithOrderInquiry(<OrderInquiryPage />, {
      seedSession: sessionWith([orderOlder, orderNewer]),
    });
    expect(await screen.findByText(/ms\. ling \(sonya@x\.com\)/i)).toBeInTheDocument();

    const labels = screen.getAllByText(/^Order #/);
    expect(labels[0]).toHaveTextContent("Order #1002"); // newer order_date first
    expect(labels[1]).toHaveTextContent("Order #1001");
  });

  it("selects an order, calls /order/init, and shows the order detail + first reply", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: orderNewer,
        response: "Your order is still in 'transit' status.",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);

    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("Your order is still in 'transit' status.")).toBeInTheDocument();
    expect(screen.getByText("transit")).toBeInTheDocument();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/support/order/init");
    const body = JSON.parse(init.body);
    expect(body.order_number_provided).toBe(1002);
    expect(body.thread_id).toBeNull();
  });

  it("does not advance to the detail screen when target_order is null", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: null,
        response: "System error!! We cannot find your order, please try it later",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);

    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(
      await screen.findByText("System error!! We cannot find your order, please try it later")
    ).toBeInTheDocument();
    // Still on the selection screen, not the chat screen.
    expect(screen.getByRole("radio")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/haven't received/i)).not.toBeInTheDocument();
  });

  it("continues the conversation and reuses thread_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderNewer,
          response: "Your order is still in 'transit' status.",
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({ thread_id: "t1", response: "We'll be happy to process the return." })
      );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    const input = screen.getByPlaceholderText(/haven't received/i);
    await userEvent.type(input, "The item is damaged, I want a refund");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("We'll be happy to process the return.")).toBeInTheDocument();

    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondBody.thread_id).toBe("t1");
    expect(secondBody.user_conversation).toBe("The item is damaged, I want a refund");
  });

  it("shows a 'Refundable' column flagging nonrefundable items with their reason", async () => {
    const orderWithIntimateItem: Order = {
      ...orderOlder,
      items: [
        { ...orderOlder.items[0] },
        {
          product_id: "P3",
          product_name: "Silk Bra",
          supplier_name: "Acme",
          unit_price: 40,
          number_units: 1,
          nonrefundable_item: true,
          nonrefundable_reason: "intimate item",
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: orderWithIntimateItem,
        response: "Your order was delivered.",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderWithIntimateItem]) });
    await screen.findByText(/order #1001/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await screen.findByText("Your order was delivered.");
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText(/no — intimate item/i)).toBeInTheDocument();
  });

  it("shows 'Like to Exchange or Return for Refund' only once the order is delivered, and navigates to the return screen", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: orderOlder,
        response: "Your order was delivered.",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderOlder]) });
    await screen.findByText(/order #1001/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order was delivered.");

    const returnButton = screen.getByRole("button", { name: /exchange or return for refund/i });
    await userEvent.click(returnButton);
    expect(push).toHaveBeenCalledWith("/customer/order-inquiry/return");
  });

  it("hides 'Like to Exchange or Return for Refund' for an order that hasn't been delivered yet", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: orderNewer,
        response: "Your order is still in 'transit' status.",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    expect(screen.queryByRole("button", { name: /exchange or return for refund/i })).not.toBeInTheDocument();
  });

  it("restarts from selection with an error when /order/continue returns 400", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderNewer,
          response: "Your order is still in 'transit' status.",
        })
      )
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ detail: "Order inquiry session not found or expired." }),
      });
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    const input = screen.getByPlaceholderText(/haven't received/i);
    await userEvent.type(input, "Still there?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/session has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("radio")).toBeInTheDocument();
  });

  it("grays out 'Back to order selection' with only one order, but offers general inquiry as an escape hatch", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        thread_id: "t1",
        target_order: orderNewer,
        response: "Your order is still in 'transit' status.",
      })
    );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    expect(screen.getByRole("button", { name: /back to order selection/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /ask a general question/i })).not.toBeDisabled();
  });

  it("lets a multi-order customer go back and pick a different order, reusing thread_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderNewer,
          response: "Your order is still in 'transit' status.",
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderOlder,
          response: "Your order is in 'delivered' status.",
        })
      );
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderOlder, orderNewer]) });
    await screen.findByText(/order #1002/i);
    const radios = screen.getAllByRole("radio");
    await userEvent.click(radios[0]); // newer order, listed first
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    const backButton = screen.getByRole("button", { name: /back to order selection/i });
    expect(backButton).not.toBeDisabled();
    await userEvent.click(backButton);

    const secondRoundRadios = await screen.findAllByRole("radio");
    await userEvent.click(secondRoundRadios[1]); // older order
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("Your order is in 'delivered' status.")).toBeInTheDocument();
    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondCallBody.thread_id).toBe("t1");
    expect(secondCallBody.order_number_provided).toBe(1001);
  });

  it("navigates to general inquiry", async () => {
    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("button", { name: /ask a general question/i }));
    expect(push).toHaveBeenCalledWith("/customer/others");
  });

  it("offers 'Ask a general question' directly on the chat screen and calls /api/support/exit before navigating away, even for a single-order customer", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderNewer,
          response: "Your order is still in 'transit' status.",
        })
      )
      .mockResolvedValueOnce(jsonResponse(null));
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    await userEvent.click(screen.getByRole("button", { name: /ask a general question/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [exitUrl, exitInit] = fetchMock.mock.calls[1];
    expect(exitUrl).toContain("/support/exit");
    expect(JSON.parse(exitInit.body)).toEqual({ thread_id: "t1" });
    expect(push).toHaveBeenCalledWith("/customer/others");
  });

  it("shows an empty state and no Continue button when the customer has no recent orders", async () => {
    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([]) });
    expect(await screen.findByText(/don't have any recent orders/i)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^continue$/i })).not.toBeInTheDocument();
  });

  it("clears the session and returns home on Exit without a thread yet", async () => {
    const fetchMock = vi.fn();
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);

    // no thread -> no /support/exit; only the server-session logout call
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/logout");
    expect(push).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("csa_session")).toBeNull();
  });

  it("calls /api/support/exit before logging out once a thread exists", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          thread_id: "t1",
          target_order: orderNewer,
          response: "Your order is still in 'transit' status.",
        })
      )
      .mockResolvedValueOnce(jsonResponse(null));
    stubFetch(fetchMock);

    renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);

    // calls: [..., /support/exit, /auth/logout (best-effort server session clear)]
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const [exitUrl, exitInit] = fetchMock.mock.calls[1];
    expect(exitUrl).toContain("/support/exit");
    expect(JSON.parse(exitInit.body)).toEqual({ thread_id: "t1" });
    expect(fetchMock.mock.calls[2][0]).toContain("/auth/logout");
    expect(push).toHaveBeenCalledWith("/");
  });

  describe("the order's refund request card (CSA-23)", () => {
    function refundRequest(overrides: Record<string, unknown> = {}) {
      return {
        refund_request_id: 7,
        request_date: "2026-08-01T00:00:00Z",
        status: "pending",
        requires_manual_approval: false,
        requires_manual_approval_reason: null,
        notes_for_human_review_override: null,
        decided_by: null,
        decision_reason: null,
        decided_date: null,
        returned_order: {
          origin_order_id: 1001,
          original_delivery_date: "2026-07-05T00:00:00Z",
          returned_date: null,
          status: "pending",
          tax_applied_rate: 0.08,
          estimated_amount_refund_incl_tax: 54,
          refurbished_amount_incl_tax: 0,
          processed_date: null,
          items: [{ product_id: "P1", product_name: "Widget", number_units: 2 }],
        },
        ...overrides,
      };
    }

    async function openDeliveredOrder(byOrder: unknown) {
      const fetchMock = vi.fn().mockResolvedValueOnce(
        jsonResponse({ thread_id: "t1", target_order: orderOlder, response: "Your order was delivered." })
      );
      stubFetch(fetchMock, byOrder);
      renderWithOrderInquiry(<OrderInquiryPage />, { seedSession: sessionWith([orderOlder]) });
      await screen.findByText(/order #1001/i);
      await userEvent.click(screen.getByRole("radio"));
      await userEvent.click(screen.getByRole("button", { name: /continue/i }));
      await screen.findByText("Your order was delivered.");
      return fetchMock;
    }

    describe("coming back to the order chat after a request was created", () => {
      function renderBack(exchanges: { question: string | null; answer: string }[], initMock: ReturnType<typeof vi.fn>) {
        stubFetch(initMock);
        renderWithOrderInquiry(<OrderInquiryPage />, {
          seedSession: sessionWith([orderOlder]),
          seedOrderInquiry: { threadId: "t1", targetOrder: orderOlder, refundRequest: refundRequest() as never, exchanges },
        });
      }

      it("replaces the stale seeded greeting by asking /order/init again on the same thread", async () => {
        const initMock = vi.fn().mockResolvedValue(
          jsonResponse({ thread_id: "t1", target_order: orderOlder, response: "You have a request that is not processed." })
        );
        renderBack([{ question: null, answer: "Is everything O.K.?" }], initMock);
        expect(await screen.findByText("You have a request that is not processed.")).toBeInTheDocument();
        expect(screen.queryByText("Is everything O.K.?")).not.toBeInTheDocument();
        expect(initMock).toHaveBeenCalledTimes(1);
        expect(JSON.parse(initMock.mock.calls[0][1].body)).toMatchObject({
          thread_id: "t1",
          order_number_provided: orderOlder.order_id,
        });
      });

      it("leaves a conversation the customer has already had alone", async () => {
        const initMock = vi.fn();
        renderBack(
          [
            { question: null, answer: "Is everything O.K.?" },
            { question: "my package is late", answer: "Sorry to hear that." },
          ],
          initMock
        );
        expect(await screen.findByText("Sorry to hear that.")).toBeInTheDocument();
        expect(initMock).not.toHaveBeenCalled();
      });
    });

    it("shows no card and keeps the exchange/return button when the order has no request", async () => {
      await openDeliveredOrder([]);
      expect(screen.queryByTestId("refund-request-card")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /like to exchange or return for refund/i })).toBeInTheDocument();
    });

    it("shows a pending request with a way to resume it, and disables the exchange/return button", async () => {
      await openDeliveredOrder([refundRequest()]);
      const card = await screen.findByTestId("refund-request-card");
      expect(card).toHaveTextContent("#7");
      expect(card).toHaveTextContent("Not processed yet");
      expect(card).toHaveTextContent("2 × Widget");
      expect(screen.queryByRole("button", { name: /like to exchange or return for refund/i })).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: /resume return request/i }));
      expect(push).toHaveBeenCalledWith("/customer/order-inquiry/return");
    });

    it("shows a decided request read-only, from a previous visit (after re-login)", async () => {
      await openDeliveredOrder([
        refundRequest({ status: "manual_approve", decided_by: "alice", decided_date: "2026-08-02T00:00:00Z", decision_reason: "Looks fine" }),
      ]);
      const card = await screen.findByTestId("refund-request-card");
      expect(card).toHaveTextContent("Approved after human review");
      expect(card).toHaveTextContent("alice");
      expect(card).toHaveTextContent("Looks fine");
      expect(screen.queryByRole("button", { name: /resume return request/i })).not.toBeInTheDocument();
    });

    it("picks the newest request if the order somehow has several", async () => {
      await openDeliveredOrder([refundRequest({ refund_request_id: 3 }), refundRequest({ refund_request_id: 9, status: "auto_approve" })]);
      expect(await screen.findByTestId("refund-request-card")).toHaveTextContent("#9");
    });

    it("refreshes the card after an order chat reply", async () => {
      const fetchMock = await openDeliveredOrder([refundRequest({ status: "wait_for_manual_review" })]);
      expect(await screen.findByTestId("refund-request-card")).toHaveTextContent("Waiting for a human review");
      fetchMock.mockResolvedValueOnce(jsonResponse({ thread_id: "t1", response: "It was approved." }));
      // the GET by id for the refresh (not by_order) goes through the queued mock too
      fetchMock.mockResolvedValueOnce(jsonResponse(refundRequest({ status: "manual_approve", decided_by: "alice" })));
      await userEvent.type(screen.getByPlaceholderText(/haven't received/i), "was my refund approved?");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      expect(await screen.findByText("It was approved.")).toBeInTheDocument();
      await waitFor(() => expect(screen.getByTestId("refund-request-card")).toHaveTextContent("Approved after human review"));
    });
  });
});
