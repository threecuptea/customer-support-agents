"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Send,
  Loader2,
  LogOut,
  ArrowLeft,
  PackageSearch,
  MessageCircleQuestion,
  Undo2,
  User,
  Bot,
} from "lucide-react";
import { useAuth, useRequireRole, Order } from "../../../lib/auth-context";
import { useOrderInquiry } from "../../../lib/order-inquiry-context";
import { RefundRequest, fetchRefundRequestForOrder, isProcessed, statusLabel } from "../../../lib/refund-request";
import { useRefundRequestSync } from "../../../lib/use-refund-request-sync";

// Backend API base URL — defaults to same-origin (single-container deploy).
// Override with NEXT_PUBLIC_API_URL at build time for other setups.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

interface OrderInitResponse {
  thread_id: string;
  target_order: Order | null;
  response: string;
}

// Mirrors backend's GenericResponse — CSA-13 dropped the order-continue-specific
// escalation_reason/intent_for_return_refund fields that used to live here; the
// customer now tells us they want to return/refund by pressing a button instead
// (see the "Like to Exchange or Return for Refund" button below).
interface GenericResponse {
  thread_id: string;
  response: string;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

// Backend does not guarantee order — sort descending by order_date ourselves.
function sortOrdersDescending(orders: Order[]): Order[] {
  return [...orders].sort(
    (a, b) => new Date(b.order_date).getTime() - new Date(a.order_date).getTime()
  );
}

function statusBadgeClasses(status: Order["status"]): string {
  switch (status) {
    case "delivered":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "transit":
      return "bg-brand-blue/10 text-brand-blue border-brand-blue/30";
    case "pending":
      return "bg-amber-50 text-amber-700 border-amber-200";
  }
}

// Exchange/return is only offered once the order has actually been delivered —
// there's nothing to return before then. Retrofitted per CSA-11's comments.
function canExchangeOrReturn(order: Order): boolean {
  return order.status === "delivered" && !!order.delivery_date;
}

// The order's refund request (CSA-23), shown under the order details whether or not the customer asks about it.
// For a request that has not been processed, the only way forward is the return screen, which resumes it
// ("Process the request" / "I like to chat"); a processed one is read-only here.
function RefundRequestCard({ rr, onResume, disabled }: { rr: RefundRequest; onResume: () => void; disabled: boolean }) {
  const items = rr.returned_order.items.map((i) => `${i.number_units} × ${i.product_name}`).join(", ");
  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6" data-testid="refund-request-card">
      <h2 className="text-sm font-semibold text-brand-navy mb-2">Return / refund request #{rr.refund_request_id}</h2>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-gray-100">
          <tr>
            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">Status</th>
            <td className="py-1">{statusLabel(rr.status)}</td>
          </tr>
          <tr>
            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">Items</th>
            <td className="py-1">{items}</td>
          </tr>
          <tr>
            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">Estimated refund (incl. tax)</th>
            <td className="py-1">{formatCurrency(rr.returned_order.estimated_amount_refund_incl_tax)}</td>
          </tr>
          {isProcessed(rr) && rr.decided_by && (
            <tr>
              <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">Decided by</th>
              <td className="py-1">
                {rr.decided_by}
                {rr.decided_date ? ` on ${formatDate(rr.decided_date)}` : ""}
              </td>
            </tr>
          )}
          {rr.decision_reason && (
            <tr>
              <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">Decision reason</th>
              <td className="py-1">{rr.decision_reason}</td>
            </tr>
          )}
        </tbody>
      </table>
      {!isProcessed(rr) && (
        <div className="mt-3">
          <p className="text-sm font-semibold text-red-700 bg-red-50 border border-red-300 rounded-lg px-3 py-2 mb-3" role="alert">
            This request has not been processed yet. Please resume it to press &quot;Process the request&quot; or
            &quot;I like to chat&quot; (to ask for a human review) before anything else.
          </p>
          <button
            onClick={onResume}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            <Undo2 className="w-4 h-4" /> Resume return request
          </button>
        </div>
      )}
      {rr.status === "wait_for_manual_review" && (
        <p className="mt-3 text-sm text-gray-600">
          A human reviewer is looking at it. You will receive an email with the result, usually within 30 minutes.
        </p>
      )}
    </div>
  );
}

export default function OrderInquiryPage() {
  const { session, isLoading } = useRequireRole("customer");
  const { logout } = useAuth();
  const router = useRouter();
  const {
    threadId,
    setThreadId,
    targetOrder,
    setTargetOrder,
    exchanges,
    setExchanges,
    resetForNewOrder,
    leaveOrderThread,
    refundRequest,
    setRefundRequest,
    greetingKnowsRequest,
    setGreetingKnowsRequest,
  } = useOrderInquiry();
  const { refresh: refreshRefundRequest } = useRefundRequestSync();

  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [conversation, setConversation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The opening reply is a static script seeded when the order was selected. If a refund request was created
  // afterwards (on the return screen), coming back would still show "Is everything O.K.?". Re-ask /order/init on the
  // same thread once: it sees the request (detect_order_revisit_node) and answers from it. Only done while the chat is
  // just that seeded reply; a conversation the customer has already had is left alone.
  const greetingAskedRef = useRef(false);
  const seedOnly = exchanges.length === 1 && exchanges[0].question === null;
  const customerForGreeting = session?.customer_context ?? null;
  useEffect(() => {
    if (!targetOrder || !refundRequest || greetingKnowsRequest || greetingAskedRef.current || !threadId || !customerForGreeting) return;
    // A ref, besides the context flag: the flag's state update has not landed yet when React (dev strict mode)
    // runs the effect a second time, which would send a second /order/init.
    greetingAskedRef.current = true;
    setGreetingKnowsRequest(true);
    if (!seedOnly) return;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/support/order/init`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            thread_id: threadId,
            customer_context: customerForGreeting,
            order_number_provided: targetOrder.order_id,
          }),
        });
        if (!res.ok) return; // keep the old reply rather than blocking the screen
        const data: OrderInitResponse = await res.json();
        if (data.target_order) setExchanges([{ question: null, answer: data.response }]);
      } catch {
        // keep the old reply
      }
    })();
  }, [targetOrder, refundRequest, greetingKnowsRequest, threadId, customerForGreeting, seedOnly, setGreetingKnowsRequest, setExchanges]);

  if (isLoading || !session) return null;

  const customer = session.customer_context;
  if (!customer) return null;

  // Derived, not stored: targetOrder already lives in shared context and
  // survives navigating to/from the return/refund screen, so re-deriving the
  // step from it (rather than tracking a separate piece of local state) means
  // coming back from that screen lands back on the chat step automatically.
  const step: "select" | "chat" = targetOrder ? "chat" : "select";
  const orders = sortOrdersDescending(customer.latest_orders);
  const canChangeOrder = orders.length > 1;
  const greetingName = `${customer.title} ${customer.last_name}`;

  const exit = async () => {
    await leaveOrderThread();
    logout();
    router.push("/");
  };

  const goToGeneralInquiry = async () => {
    await leaveOrderThread();
    router.push("/customer/others");
  };

  const goToExchangeOrReturn = () => {
    router.push("/customer/order-inquiry/return");
  };

  const backToSelection = () => {
    resetForNewOrder();
    setSelectedOrderId(null);
    setConversation("");
    setError(null);
  };

  const selectOrder = async () => {
    if (selectedOrderId == null) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/order/init`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          customer_context: customer,
          order_number_provided: selectedOrderId,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: OrderInitResponse = await res.json();
      setThreadId(data.thread_id);
      if (!data.target_order) {
        // Contract: never advance to the detail/chat screen without a target_order.
        setError(data.response);
        return;
      }
      setTargetOrder(data.target_order);
      setExchanges([{ question: null, answer: data.response }]);
      // The agent keeps one refund request per order; load it (also after a logout/ re-login) so the card shows.
      // undefined = the call failed: leave it empty rather than blocking the order chat.
      const existing = (await fetchRefundRequestForOrder(data.target_order.order_id)) ?? null;
      setRefundRequest(existing);
      // /order/init above ran before this read, so it saw the request only if one already existed. With none, the
      // reply is the static script and goes stale once a request is created on the return screen.
      setGreetingKnowsRequest(existing !== null);
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = async () => {
    const trimmed = conversation.trim();
    if (!trimmed || !threadId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/order/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, user_conversation: trimmed }),
      });
      if (res.status === 400) {
        // Thread expired/was never initialized — restart from order selection.
        backToSelection();
        setThreadId(null);
        setError("Your order inquiry session has expired. Please select your order again.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GenericResponse = await res.json();
      setExchanges((prev) => [...prev, { question: trimmed, answer: data.response }]);
      setConversation("");
      // The reply may have been generated from a request a Slack review just decided: refresh the card to match.
      void refreshRefundRequest();
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 py-10 px-4">
      <div className={step === "select" ? "max-w-4xl mx-auto" : "max-w-2xl mx-auto"}>
        <div className="flex items-center justify-between mb-6">
          <span className="text-sm font-semibold text-brand-navy">e-shopping.com</span>
          <button
            onClick={exit}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 disabled:opacity-50 transition-colors"
          >
            <LogOut className="w-4 h-4" /> Exit
          </button>
        </div>

        {step === "select" && (
          <>
            <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-2">
              <PackageSearch className="w-6 h-6 text-brand-purple" /> Order inquiry &amp; return refund
            </h1>
            <p className="text-brand-gray text-sm mb-1">
              {greetingName} ({customer.email})
            </p>
            <p className="text-brand-gray text-sm mb-6">
              Please select the order you&apos;re concerned about.
            </p>

            {error && (
              <div className="mb-6 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                {error}
              </div>
            )}

            {orders.length === 0 ? (
              <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-5 mb-6 text-sm text-brand-gray text-center">
                You don&apos;t have any recent orders to inquire about.
              </div>
            ) : (
              <>
                <div className="space-y-3 mb-6">
                  {orders.map((order) => (
                    <label
                      key={order.order_id}
                      className={`flex items-start gap-3 bg-white border rounded-xl shadow-soft p-4 cursor-pointer transition-colors ${
                        selectedOrderId === order.order_id
                          ? "border-brand-purple ring-1 ring-brand-purple"
                          : "border-gray-100"
                      }`}
                    >
                      <input
                        type="radio"
                        name="order-select"
                        value={order.order_id}
                        checked={selectedOrderId === order.order_id}
                        onChange={() => setSelectedOrderId(order.order_id)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="flex items-center justify-between flex-wrap gap-1">
                          <span className="font-semibold text-brand-navy">Order #{order.order_id}</span>
                          <span className="text-sm text-brand-gray">{formatDate(order.order_date)}</span>
                        </div>
                        <div className="text-sm text-brand-gray mt-0.5">
                          Total: {formatCurrency(order.total_amount_incl_tax)}
                        </div>
                        <ul className="mt-2 text-sm text-gray-700 space-y-0.5">
                          {order.items.map((item) => (
                            <li key={item.product_id}>
                              {item.product_name} × {item.number_units}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </label>
                  ))}
                </div>

                <div className="flex justify-center mb-6">
                  <button
                    onClick={selectOrder}
                    disabled={loading || selectedOrderId == null}
                    className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    {loading ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <PackageSearch className="w-4 h-4" />
                    )}
                    Continue
                  </button>
                </div>
              </>
            )}

            <div className="flex flex-wrap justify-center gap-3">
              <button
                onClick={goToGeneralInquiry}
                disabled={loading}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <MessageCircleQuestion className="w-4 h-4" /> Ask a general question
              </button>
              <button
                onClick={exit}
                disabled={loading}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <LogOut className="w-4 h-4" /> Exit
              </button>
            </div>
          </>
        )}

        {step === "chat" && targetOrder && (
          <>
            <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-4">
              <PackageSearch className="w-6 h-6 text-brand-purple" /> Order #{targetOrder.order_id}
            </h1>

            <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6 overflow-x-auto">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-gray-100">
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Status
                    </th>
                    <td className="py-1.5">
                      <span
                        className={`inline-block text-xs font-medium rounded-full px-2.5 py-0.5 border ${statusBadgeClasses(targetOrder.status)}`}
                      >
                        {targetOrder.status}
                      </span>
                    </td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Order date
                    </th>
                    <td className="py-1.5">{formatDate(targetOrder.order_date)}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Ship date
                    </th>
                    <td className="py-1.5">{formatDate(targetOrder.ship_date)}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Estimated delivery
                    </th>
                    <td className="py-1.5">{formatDate(targetOrder.estimated_delivery_date)}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Delivered on
                    </th>
                    <td className="py-1.5">{formatDate(targetOrder.delivery_date)}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Tracking number
                    </th>
                    <td className="py-1.5">{targetOrder.tracking_number ?? "—"}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Notes
                    </th>
                    <td className="py-1.5">{targetOrder.notes ?? "—"}</td>
                  </tr>
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                      Total (incl. tax)
                    </th>
                    <td className="py-1.5">{formatCurrency(targetOrder.total_amount_incl_tax)}</td>
                  </tr>
                </tbody>
              </table>

              <table className="w-full text-sm mt-3 border-t border-gray-100 pt-2">
                <thead>
                  <tr>
                    <th className="py-1.5 text-left font-medium text-gray-600">Item</th>
                    <th className="py-1.5 text-right font-medium text-gray-600">Qty</th>
                    <th className="py-1.5 text-left font-medium text-gray-600 pl-3">Refundable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {targetOrder.items.map((item) => (
                    <tr key={item.product_id}>
                      <td className="py-1.5">{item.product_name}</td>
                      <td className="py-1.5 text-right">{item.number_units}</td>
                      <td className="py-1.5 pl-3">
                        {item.nonrefundable_item ? (
                          <span className="inline-block text-xs font-medium rounded-full px-2 py-0.5 border bg-red-50 text-red-700 border-red-200">
                            No{item.nonrefundable_reason ? ` — ${item.nonrefundable_reason}` : ""}
                          </span>
                        ) : (
                          <span className="inline-block text-xs font-medium rounded-full px-2 py-0.5 border bg-emerald-50 text-emerald-700 border-emerald-200">
                            Yes
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {refundRequest && (
              <RefundRequestCard rr={refundRequest} onResume={goToExchangeOrReturn} disabled={loading} />
            )}

            <div className="space-y-4 mb-6">
              {exchanges.map((exchange, i) => (
                <div key={i} className="space-y-2">
                  {exchange.question && (
                    <div className="flex items-start gap-2 justify-end">
                      <div className="bg-brand-purple text-white rounded-lg rounded-tr-none px-3 py-2 text-sm max-w-[85%] break-words">
                        {exchange.question}
                      </div>
                      <User className="w-5 h-5 text-brand-purple shrink-0 mt-1" />
                    </div>
                  )}
                  <div className="flex items-start gap-2">
                    <Bot className="w-5 h-5 text-brand-blue shrink-0 mt-1" />
                    <div className="bg-white border border-gray-100 rounded-lg rounded-tl-none px-3 py-2 text-sm text-gray-800 max-w-[85%] break-words shadow-soft">
                      {exchange.answer}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {error && (
              <div className="mb-6 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                {error}
              </div>
            )}

            <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                What would you like to ask about this order?
              </label>
              <div className="flex gap-2">
                <input
                  value={conversation}
                  onChange={(e) => setConversation(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !loading && sendMessage()}
                  disabled={loading}
                  placeholder="e.g. I haven't received my package yet"
                  className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
                />
                <button
                  onClick={sendMessage}
                  disabled={loading || !conversation.trim()}
                  className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  Send
                </button>
              </div>
            </div>

            <div className="flex flex-wrap justify-center gap-3">
              {/* One CSA refund request per order: once it exists the button is disabled (hidden); a further return goes to a CSR. */}
              {canExchangeOrReturn(targetOrder) && !refundRequest && (
                <button
                  onClick={goToExchangeOrReturn}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  <Undo2 className="w-4 h-4" /> Like to Exchange or Return for Refund
                </button>
              )}
              <button
                onClick={backToSelection}
                disabled={!canChangeOrder || loading}
                title={canChangeOrder ? undefined : "You have only one recent order."}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <ArrowLeft className="w-4 h-4" /> Back to order selection
              </button>
              <button
                onClick={goToGeneralInquiry}
                disabled={loading}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <MessageCircleQuestion className="w-4 h-4" /> Ask a general question
              </button>
              <button
                onClick={exit}
                disabled={loading}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <LogOut className="w-4 h-4" /> Exit
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
