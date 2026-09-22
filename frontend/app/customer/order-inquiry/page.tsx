"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Send,
  Loader2,
  LogOut,
  ArrowLeft,
  PackageSearch,
  MessageCircleQuestion,
  User,
  Bot,
  Undo2,
} from "lucide-react";
import { useAuth, useRequireRole, Order } from "../../../lib/auth-context";

// Backend API base URL — defaults to same-origin (single-container deploy).
// Override with NEXT_PUBLIC_API_URL at build time for other setups.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

interface OrderInitResponse {
  thread_id: string;
  target_order: Order | null;
  response: string;
}

interface OrderContinueResponse {
  thread_id: string;
  response: string;
  escalation_reason: string | null;
  intent_for_return_refund: boolean;
}

interface Exchange {
  question: string | null; // null for the deterministic first reply from /order/init
  answer: string;
  intentForReturnRefund?: boolean;
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

export default function OrderInquiryPage() {
  const { session, isLoading } = useRequireRole("customer");
  const { logout } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState<"select" | "chat">("select");
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [targetOrder, setTargetOrder] = useState<Order | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [conversation, setConversation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isLoading || !session) return null;

  const customer = session.customer_context;
  if (!customer) return null;

  const orders = sortOrdersDescending(customer.latest_orders);
  const canChangeOrder = orders.length > 1;
  const greetingName = `${customer.title} ${customer.last_name}`;

  // Best-effort: tells the backend to summarize this order thread before it's
  // abandoned (Exit, or navigating away to a different support flow). Never
  // blocks the caller on failure.
  const leaveOrderThread = async () => {
    if (!threadId) return;
    try {
      await fetch(`${API_URL}/support/exit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId }),
      });
    } catch {
      // Best-effort: never block navigation on this call failing.
    }
  };

  const exit = async () => {
    await leaveOrderThread();
    logout();
    router.push("/");
  };

  const goToGeneralInquiry = async () => {
    await leaveOrderThread();
    router.push("/customer/others");
  };

  const backToSelection = () => {
    setStep("select");
    setTargetOrder(null);
    setExchanges([]);
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
      setStep("chat");
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
      const data: OrderContinueResponse = await res.json();
      setExchanges((prev) => [
        ...prev,
        {
          question: trimmed,
          answer: data.response,
          intentForReturnRefund: data.intent_for_return_refund,
        },
      ]);
      setConversation("");
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
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {targetOrder.items.map((item) => (
                    <tr key={item.product_id}>
                      <td className="py-1.5">{item.product_name}</td>
                      <td className="py-1.5 text-right">{item.number_units}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

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
                    <div className="space-y-1">
                      <div className="bg-white border border-gray-100 rounded-lg rounded-tl-none px-3 py-2 text-sm text-gray-800 max-w-[85%] break-words shadow-soft">
                        {exchange.answer}
                      </div>
                      {exchange.intentForReturnRefund && (
                        // Temporary marker until the return/refund ticket builds the real
                        // itemized-return screen — tear down once that lands.
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-brand-purple bg-brand-purple/10 border border-brand-purple/30 rounded-full px-2 py-0.5">
                          <Undo2 className="w-3 h-3" /> Return requested
                        </span>
                      )}
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
