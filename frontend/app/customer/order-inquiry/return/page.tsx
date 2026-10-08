"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Send,
  Loader2,
  LogOut,
  ArrowLeft,
  ClipboardList,
  ShieldCheck,
  Receipt,
  RotateCcw,
  MessageCircleQuestion,
  User,
  Bot,
} from "lucide-react";
import { useAuth, useRequireRole, Order } from "../../../../lib/auth-context";
import { useOrderInquiry } from "../../../../lib/order-inquiry-context";
import { EXCHANGE_RETURN_REASONS } from "../../../../lib/exchange-return-reasons";
import { RETURN_POLICY } from "../../../../lib/return-policy";

// Backend API base URL — defaults to same-origin (single-container deploy).
// Override with NEXT_PUBLIC_API_URL at build time for other setups.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// Short display labels for the survey radios — purely UI copy, not sent to the
// backend (the submitted `reason_option` is EXCHANGE_RETURN_REASONS' `value`,
// generated from the backend enum so it can't drift). Keyed by enum member name.
const REASON_LABELS: Record<string, string> = {
  WRONG_SIZE_OR_FIT: "Wrong size or fit",
  NOT_MATCH_DESCRIPTION_OR_PHOTO: "Doesn't match description or photos",
  DAMAGED_DEFECTIVE_OR_MISSING_PARTS: "Damaged, defective, or missing parts",
  CHANGED_MIND_OR_IMPULSE_BUY: "Changed my mind / impulse buy",
  LATE_DELIVERY_NO_LONGER_NEEDED: "Late delivery, no longer needed",
  WRONG_ITEM_SHIPPED: "Wrong item shipped",
  BETTER_PRICE_FOUND: "Found a better price elsewhere",
  DIFFICULT_TO_ASSEMBLY: "Difficult to assemble or use",
  DIFFERENT_COLOR_OR_STYLE: "Want a different color or style",
  OTHERS: "Others",
};
const OTHERS_KEY = "OTHERS";

// Mirrors backend models/model.py. order_refund_status/status are full
// descriptive sentences (StrEnum values), not short codes — displayed as-is.
interface ReturnRefundInitialDecision {
  order_refund_status: string;
}
interface ReturnedOrder {
  origin_order_id: number;
  original_delivery_date: string;
  returned_date: string | null;
  status: "returned" | "pending";
  tax_applied_rate: number;
  estimated_amount_refund_incl_tax: number;
  refurbished_amount_incl_tax: number;
  processed_date: string | null;
}
interface RefundRequest {
  refund_request_id: number;
  request_date: string;
  status: string;
  requires_manual_approval: boolean;
  requires_manual_approval_reason: string | null;
  notes_for_human_review_override: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  decided_date: string | null;
  returned_order: ReturnedOrder;
}
interface InitialReturnRefundResponse {
  thread_id: string;
  response: string;
  initial_return_refund_decision: ReturnRefundInitialDecision;
  refund_request_to_process: RefundRequest | null;
}
interface ReturnRefundProcessResponse {
  thread_id: string;
  response: string;
  refund_request_to_process: RefundRequest;
  assigned_refund_request_id: number;
}
interface ReturnRefundChatResponse {
  thread_id: string;
  response: string;
  request_human_review_return_refund: boolean;
}
interface GenericResponse {
  thread_id: string;
  response: string;
}
interface ChatExchange {
  question: string;
  answer: string;
}

function canExchangeOrReturn(order: Order): boolean {
  return order.status === "delivered" && !!order.delivery_date;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

function formatPercent(rate: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 2 }).format(rate);
}

type ItemSelection = { selected: boolean; qty: number };

function initialSelections(order: Order | null): Record<string, ItemSelection> {
  if (!order) return {};
  return Object.fromEntries(
    order.items.map((item) => [item.product_id, { selected: false, qty: item.number_units }])
  );
}

export default function ExchangeReturnPage() {
  const { session, isLoading } = useRequireRole("customer");
  const { logout } = useAuth();
  const router = useRouter();
  const { threadId, targetOrder, exchangeReturnSurvey, markExchangeReturnSurveyDone, leaveOrderThread } =
    useOrderInquiry();

  // Guard: this screen only makes sense mid-visit, right after the customer
  // picked a delivered order on the order-inquiry screen. A direct reload/URL
  // visit loses the in-memory context (same as the chat screen already does
  // today), so send the customer back rather than rendering with nothing to
  // show.
  const eligible = !!targetOrder && canExchangeOrReturn(targetOrder);
  useEffect(() => {
    if (!isLoading && session && !eligible) {
      router.replace("/customer/order-inquiry");
    }
  }, [isLoading, session, eligible, router]);

  const [step, setStep] = useState<"survey" | "policy" | "process">("survey");

  // CSA-14 — survey
  const [reasonKey, setReasonKey] = useState<string | null>(exchangeReturnSurvey.reasonKey);
  const [otherText, setOtherText] = useState(exchangeReturnSurvey.otherText);

  // CSA-15 — policy acknowledgment
  const [policyAcknowledged, setPolicyAcknowledged] = useState(false);

  // CSA-16 — itemized return + decision/process/chat
  const [itemSelections, setItemSelections] = useState<Record<string, ItemSelection>>(() =>
    initialSelections(targetOrder)
  );
  const [initialDecision, setInitialDecision] = useState<ReturnRefundInitialDecision | null>(null);
  const [refundRequest, setRefundRequest] = useState<RefundRequest | null>(null);
  const [decisionResponse, setDecisionResponse] = useState<string | null>(null);
  const [chatMode, setChatMode] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatExchanges, setChatExchanges] = useState<ChatExchange[]>([]);
  const [requestHumanReview, setRequestHumanReview] = useState(false);
  const [reviewNotes, setReviewNotes] = useState("");
  const [assignedRefundRequestId, setAssignedRefundRequestId] = useState<number | null>(null);
  const [processResponse, setProcessResponse] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isLoading || !session || !eligible) return null;

  const itemsEditable = !initialDecision;
  const processed = assignedRefundRequestId != null;

  const exit = async () => {
    await leaveOrderThread();
    logout();
    router.push("/");
  };

  const backToOrderChat = () => router.push("/customer/order-inquiry");

  const submitSurvey = async () => {
    if (!threadId || !reasonKey) return;
    const reason = EXCHANGE_RETURN_REASONS.find((r) => r.key === reasonKey);
    if (!reason) return;
    if (reasonKey === OTHERS_KEY && !otherText.trim()) {
      setError("Please describe your reason in the box below.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/exchange_return/recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          reason_option: reason.value,
          reason_input: reasonKey === OTHERS_KEY ? otherText.trim() : null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GenericResponse & { special_exchange_handling?: boolean } = await res.json();
      markExchangeReturnSurveyDone(reasonKey, otherText, data.response, data.special_exchange_handling ?? false);
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const toggleItem = (productId: string, maxQty: number) => {
    setItemSelections((prev) => {
      const current = prev[productId];
      const nextSelected = !current.selected;
      return { ...prev, [productId]: { selected: nextSelected, qty: nextSelected ? current.qty : maxQty } };
    });
  };

  const setItemQty = (productId: string, qty: number, maxQty: number) => {
    const clamped = Math.min(Math.max(1, qty || 1), maxQty);
    setItemSelections((prev) => ({ ...prev, [productId]: { ...prev[productId], qty: clamped } }));
  };

  const submitItemize = async () => {
    if (!threadId) return;
    const items = Object.entries(itemSelections)
      .filter(([, v]) => v.selected)
      .map(([product_id, v]) => ({ product_id, qty: v.qty }));
    if (items.length === 0) {
      setError("Select at least one item to return, with a valid quantity.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/return_refund/init`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, items }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(body?.detail ?? `HTTP ${res.status}`);
        return;
      }
      const data: InitialReturnRefundResponse = await res.json();
      setInitialDecision(data.initial_return_refund_decision);
      setRefundRequest(data.refund_request_to_process);
      setDecisionResponse(data.response);
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const resetItemizeInput = () => {
    setInitialDecision(null);
    setRefundRequest(null);
    setDecisionResponse(null);
    setChatMode(false);
    setChatInput("");
    setChatExchanges([]);
    setRequestHumanReview(false);
    setReviewNotes("");
    setError(null);
  };

  const sendReturnRefundChat = async () => {
    const trimmed = chatInput.trim();
    if (!trimmed || !threadId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/return_refund/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, user_conversation: trimmed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ReturnRefundChatResponse = await res.json();
      setChatExchanges((prev) => [...prev, { question: trimmed, answer: data.response }]);
      setRequestHumanReview(data.request_human_review_return_refund);
      setChatInput("");
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const processRequest = async () => {
    if (!threadId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/return_refund/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          notes_for_human_review_override: requestHumanReview ? reviewNotes.trim() || null : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(body?.detail ?? `HTTP ${res.status}`);
        return;
      }
      const data: ReturnRefundProcessResponse = await res.json();
      setRefundRequest(data.refund_request_to_process);
      setAssignedRefundRequestId(data.assigned_refund_request_id);
      setProcessResponse(data.response);
    } catch {
      setError("Could not reach support. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 py-10 px-4">
      <div className="max-w-2xl mx-auto">
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

        {step === "survey" && (
          <>
            <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-2">
              <ClipboardList className="w-6 h-6 text-brand-purple" /> Exchange / Return reason survey
            </h1>
            <p className="text-brand-gray text-sm mb-6">
              Please fill out a short survey then press &ldquo;Submit the survey&rdquo; button. That
              will help us better serve you and improve e-shopping.com. We will provide a
              recommendation and instruction as well. If you revisit for the same order and already
              filled out the survey, you can press &ldquo;Start return for refund process&rdquo; to
              bypass instead.
            </p>

            <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6 space-y-2">
              {EXCHANGE_RETURN_REASONS.map((reason) => (
                <label
                  key={reason.key}
                  className="flex items-start gap-2.5 py-1 cursor-pointer text-sm text-gray-800"
                >
                  <input
                    type="radio"
                    name="exchange-return-reason"
                    checked={reasonKey === reason.key}
                    disabled={exchangeReturnSurvey.done}
                    onChange={() => setReasonKey(reason.key)}
                    className="mt-0.5"
                  />
                  {REASON_LABELS[reason.key] ?? reason.key}
                </label>
              ))}
              {reasonKey === OTHERS_KEY && (
                <input
                  value={otherText}
                  onChange={(e) => setOtherText(e.target.value)}
                  disabled={exchangeReturnSurvey.done}
                  placeholder="Please describe your reason"
                  className="w-full mt-2 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
                />
              )}
            </div>

            {exchangeReturnSurvey.recommendation && (
              <div className="mb-6 text-sm text-left align-top text-gray-800 bg-brand-blue/10 border border-brand-blue/30 rounded-lg p-3 whitespace-pre-wrap">
                {exchangeReturnSurvey.recommendation.trim()}
              </div>
            )}

            {error && (
              <div className="mb-6 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                {error}
              </div>
            )}

            <div className="flex flex-wrap justify-center gap-3">
              <button
                onClick={submitSurvey}
                disabled={
                  loading ||
                  exchangeReturnSurvey.done ||
                  !reasonKey ||
                  (reasonKey === OTHERS_KEY && !otherText.trim())
                }
                className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                Submit the survey
              </button>
              {!exchangeReturnSurvey.specialExchangeHandling && (
                <button
                  onClick={() => setStep("policy")}
                  disabled={!exchangeReturnSurvey.done || loading}
                  className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  Start return for refund process
                </button>
              )}
              <button
                onClick={backToOrderChat}
                disabled={loading}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <ArrowLeft className="w-4 h-4" /> Return to order details/ chat
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

        {step === "policy" && (
          <>
            <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-4">
              <ShieldCheck className="w-6 h-6 text-brand-purple" /> Return Policy
            </h1>
            <p className="text-brand-gray text-sm mb-4">
              Please scroll down and read the full return policy, check &ldquo;I confirm that I have
              read and understand the terms of the return policy&rdquo;, then click the
              &ldquo;Acknowledge &amp; Proceed&rdquo; button to advance.
            </p>

            <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6 text-sm text-gray-800 whitespace-pre-wrap">
              {RETURN_POLICY.trim()}
            </div>

            <label className="flex items-start gap-2.5 text-sm text-gray-800 mb-6 cursor-pointer">
              <input
                type="checkbox"
                checked={policyAcknowledged}
                onChange={(e) => setPolicyAcknowledged(e.target.checked)}
                className="mt-0.5"
              />
              I confirm that I have read and understand the terms of the return policy.
            </label>

            <div className="flex flex-wrap justify-center gap-3">
              <button
                onClick={() => setStep("process")}
                disabled={!policyAcknowledged}
                className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                Acknowledge &amp; Proceed
              </button>
              <button
                onClick={backToOrderChat}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <ArrowLeft className="w-4 h-4" /> Cancel
              </button>
            </div>
          </>
        )}

        {step === "process" && targetOrder && (
          <>
            <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-4">
              <Receipt className="w-6 h-6 text-brand-purple" /> Return/ Refund for Order #{targetOrder.order_id}
            </h1>

            <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-600">
                    <th className="py-1.5 pr-2"></th>
                    <th className="py-1.5 pr-3">Product</th>
                    <th className="py-1.5 pr-3">Supplier</th>
                    <th className="py-1.5 pr-3 text-right">Unit price</th>
                    <th className="py-1.5 pr-3 text-right">Ordered qty</th>
                    <th className="py-1.5 pr-3 text-right">Return qty</th>
                    <th className="py-1.5">Refundable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {targetOrder.items.map((item) => {
                    const selection = itemSelections[item.product_id];
                    return (
                      <tr key={item.product_id}>
                        <td className="py-1.5 pr-2">
                          <input
                            type="checkbox"
                            checked={selection?.selected ?? false}
                            disabled={!itemsEditable}
                            onChange={() => toggleItem(item.product_id, item.number_units)}
                          />
                        </td>
                        <td className="py-1.5 pr-3">
                          {item.product_name}
                          <div className="text-xs text-brand-gray">{item.product_id}</div>
                        </td>
                        <td className="py-1.5 pr-3">{item.supplier_name}</td>
                        <td className="py-1.5 pr-3 text-right">{formatCurrency(item.unit_price)}</td>
                        <td className="py-1.5 pr-3 text-right">{item.number_units}</td>
                        <td className="py-1.5 pr-3 text-right">
                          <input
                            type="number"
                            min={1}
                            max={item.number_units}
                            value={selection?.qty ?? item.number_units}
                            disabled={!itemsEditable || !selection?.selected}
                            onChange={(e) =>
                              setItemQty(item.product_id, parseInt(e.target.value, 10), item.number_units)
                            }
                            className="w-16 rounded-lg border border-gray-200 px-2 py-1 text-right text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
                          />
                        </td>
                        <td className="py-1.5">
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
                    );
                  })}
                </tbody>
              </table>
            </div>

            {itemsEditable && (
              <div className="flex flex-wrap justify-center gap-3 mb-6">
                <button
                  onClick={submitItemize}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  Submit
                </button>
                <button
                  onClick={backToOrderChat}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  <ArrowLeft className="w-4 h-4" /> Cancel
                </button>
              </div>
            )}

            {error && (
              <div className="mb-6 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                {error}
              </div>
            )}

            {initialDecision && (
              <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6 space-y-3">
                <div className="text-sm font-medium text-brand-navy">
                  {initialDecision.order_refund_status}
                </div>

                {refundRequest && (
                  <table className="w-full text-sm">
                    <tbody className="divide-y divide-gray-100">
                      <tr>
                        <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                          Order #
                        </th>
                        <td className="py-1">{refundRequest.returned_order.origin_order_id}</td>
                      </tr>
                      <tr>
                        <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                          Delivered on
                        </th>
                        <td className="py-1">{formatDate(refundRequest.returned_order.original_delivery_date)}</td>
                      </tr>
                      <tr>
                        <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                          Estimated refund (incl. tax)
                        </th>
                        <td className="py-1">
                          {formatCurrency(refundRequest.returned_order.estimated_amount_refund_incl_tax)}
                        </td>
                      </tr>
                      <tr>
                        <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                          Tax rate
                        </th>
                        <td className="py-1">{formatPercent(refundRequest.returned_order.tax_applied_rate)}</td>
                      </tr>
                      <tr>
                        <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                          Status
                        </th>
                        <td className="py-1">{refundRequest.status}</td>
                      </tr>
                      {processed && (
                        <>
                          <tr>
                            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                              Decided by
                            </th>
                            <td className="py-1">{refundRequest.decided_by ?? "—"}</td>
                          </tr>
                          <tr>
                            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                              Decided on
                            </th>
                            <td className="py-1">{formatDate(refundRequest.decided_date)}</td>
                          </tr>
                          <tr>
                            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                              Decision reason
                            </th>
                            <td className="py-1">{refundRequest.decision_reason ?? "—"}</td>
                          </tr>
                          {refundRequest.requires_manual_approval && (
                            <tr>
                              <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                                Manual approval
                              </th>
                              <td className="py-1">{refundRequest.requires_manual_approval_reason ?? "Required"}</td>
                            </tr>
                          )}
                          {refundRequest.notes_for_human_review_override && (
                            <tr>
                              <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                                Your notes to the reviewer
                              </th>
                              <td className="py-1">{refundRequest.notes_for_human_review_override}</td>
                            </tr>
                          )}
                          <tr>
                            <th className="py-1 pr-3 text-left font-medium text-gray-600 whitespace-nowrap">
                              Refund request #
                            </th>
                            <td className="py-1">{assignedRefundRequestId}</td>
                          </tr>
                        </>
                      )}
                    </tbody>
                  </table>
                )}

                {(processResponse ?? decisionResponse) && (
                  <div className="text-sm text-left align-top text-gray-800 bg-brand-blue/10 border border-brand-blue/30 rounded-lg p-3 whitespace-pre-wrap">
                    {(processResponse ?? decisionResponse)?.trim()}
                  </div>
                )}
              </div>
            )}

            {chatMode && (
              <div className="space-y-4 mb-6">
                {chatExchanges.map((exchange, i) => (
                  <div key={i} className="space-y-2">
                    <div className="flex items-start gap-2 justify-end">
                      <div className="bg-brand-purple text-white rounded-lg rounded-tr-none px-3 py-2 text-sm max-w-[85%] break-words">
                        {exchange.question}
                      </div>
                      <User className="w-5 h-5 text-brand-purple shrink-0 mt-1" />
                    </div>
                    <div className="flex items-start gap-2">
                      <Bot className="w-5 h-5 text-brand-blue shrink-0 mt-1" />
                      <div className="bg-white border border-gray-100 rounded-lg rounded-tl-none px-3 py-2 text-sm text-gray-800 max-w-[85%] break-words shadow-soft">
                        {exchange.answer}
                      </div>
                    </div>
                  </div>
                ))}

                <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      What would you like to ask about your return/ refund?
                    </label>
                    <div className="flex gap-2">
                      <input
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && !loading && sendReturnRefundChat()}
                        disabled={loading}
                        placeholder="e.g. Can a human review my request?"
                        className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
                      />
                      <button
                        onClick={sendReturnRefundChat}
                        disabled={loading || !chatInput.trim()}
                        className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                      >
                        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                        Send
                      </button>
                    </div>
                </div>
              </div>
            )}

            {requestHumanReview && !processed && (
              <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  The notes to a human reviewer: write in your own words why your request should be
                  approved.
                </label>
                <textarea
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  disabled={loading}
                  rows={3}
                  placeholder="e.g. I never wore the item and want to return it right away..."
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
                />
              </div>
            )}

            <div className="flex flex-wrap justify-center gap-3">
              {!itemsEditable && !processed && (
                <>
                  <button
                    onClick={processRequest}
                    disabled={loading || !refundRequest}
                    className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Receipt className="w-4 h-4" />}
                    Process the request
                  </button>
                  <button
                    onClick={backToOrderChat}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" /> Cancel
                  </button>
                  <button
                      onClick={() => setChatMode(true)}
                      disabled={loading || !refundRequest || chatMode}
                      className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                    >
                      <MessageCircleQuestion className="w-4 h-4" /> I like to chat
                    </button>
                  <button
                    onClick={resetItemizeInput}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    <RotateCcw className="w-4 h-4" /> Reset Input
                  </button>
                </>
              )}

              {processed && (
                <>
                  <button
                      onClick={() => setChatMode(true)}
                      disabled={loading || !refundRequest || chatMode}
                      className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                    >
                      <MessageCircleQuestion className="w-4 h-4" /> I like to chat
                    </button>
                  <button
                    onClick={backToOrderChat}
                    className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" /> Back to order details
                  </button>
                  <button
                    onClick={exit}
                    className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    <LogOut className="w-4 h-4" /> Exit
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
