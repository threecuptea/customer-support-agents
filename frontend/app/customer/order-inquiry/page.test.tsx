import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth, jsonResponse } from "../../../lib/test-utils";
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
      intimate_item: false,
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
      intimate_item: false,
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

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  vi.restoreAllMocks();
});

describe("OrderInquiryPage", () => {
  it("redirects to / when there is no customer session", async () => {
    renderWithAuth(<OrderInquiryPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("lists orders sorted descending by order_date, with customer name and email", async () => {
    renderWithAuth(<OrderInquiryPage />, {
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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

  it("continues the conversation, reuses thread_id, and shows the return-intent badge", async () => {
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
          response: "We'll be happy to process the return.",
          escalation_reason: null,
          intent_for_return_refund: true,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    const input = screen.getByPlaceholderText(/haven't received/i);
    await userEvent.type(input, "The item is damaged, I want a refund");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("We'll be happy to process the return.")).toBeInTheDocument();
    expect(screen.getByText(/return requested/i)).toBeInTheDocument();

    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondBody.thread_id).toBe("t1");
    expect(secondBody.user_conversation).toBe("The item is damaged, I want a refund");
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderOlder, orderNewer]) });
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
    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
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
    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([]) });
    expect(await screen.findByText(/don't have any recent orders/i)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^continue$/i })).not.toBeInTheDocument();
  });

  it("clears the session and returns home on Exit without a thread yet", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);

    expect(fetchMock).not.toHaveBeenCalled();
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
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<OrderInquiryPage />, { seedSession: sessionWith([orderNewer]) });
    await screen.findByText(/order #1002/i);
    await userEvent.click(screen.getByRole("radio"));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText("Your order is still in 'transit' status.");

    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [exitUrl, exitInit] = fetchMock.mock.calls[1];
    expect(exitUrl).toContain("/support/exit");
    expect(JSON.parse(exitInit.body)).toEqual({ thread_id: "t1" });
    expect(push).toHaveBeenCalledWith("/");
  });
});
