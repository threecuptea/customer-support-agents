// Shared refund-request types and fetch helpers (CSA-23). The refund request used to live only in
// return/page.tsx's local state, so a status changed behind our back (a Slack human review) never reached the
// screen. It now lives in OrderInquiryProvider and is refreshed from the backend (Redis is the source of truth).

// Backend API base URL — defaults to same-origin (single-container deploy).
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

export interface ReturnedOrderItem {
  product_id: string;
  product_name: string;
  number_units: number;
}

// Mirrors backend models/customer_support_model.py.
export interface ReturnedOrder {
  origin_order_id: number;
  original_delivery_date: string;
  returned_date: string | null;
  status: "returned" | "pending";
  tax_applied_rate: number;
  estimated_amount_refund_incl_tax: number;
  refurbished_amount_incl_tax: number;
  processed_date: string | null;
  items: ReturnedOrderItem[];
}

export interface RefundRequest {
  refund_request_id: number;
  request_date: string;
  status: string; // pending | auto_approve | auto_reject | wait_for_manual_review | manual_approve | manual_reject | manual_flag
  requires_manual_approval: boolean;
  requires_manual_approval_reason: string | null;
  notes_for_human_review_override: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  decided_date: string | null;
  // The decision the customer was told when the request was created (audit record); null for old records.
  initial_decision?: string | null;
  returned_order: ReturnedOrder;
}

// `rr_being_processed` exists only on /init and /process responses, so after a refresh "processed" is
// derived from the status: a request is processed as soon as it is no longer `pending`.
export function isProcessed(rr: RefundRequest | null | undefined): boolean {
  return !!rr && rr.status !== "pending";
}

export const WAITING_FOR_REVIEW = "wait_for_manual_review";

// Short customer-facing wording for each status.
export function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "Not processed yet";
    case "wait_for_manual_review":
      return "Waiting for a human review";
    case "auto_approve":
      return "Approved";
    case "auto_reject":
      return "Rejected";
    case "manual_approve":
      return "Approved after human review";
    case "manual_reject":
      return "Rejected after human review";
    case "manual_flag":
      return "Flagged for follow-up";
    default:
      return status;
  }
}

// GET /return_refund/{id}. Returns the request, null when the backend says it is missing or not ours,
// or undefined when the call failed — callers keep their last known state in both of the latter cases.
export async function fetchRefundRequest(refundRequestId: number): Promise<RefundRequest | null | undefined> {
  try {
    const res = await fetch(`${API_URL}/support/return_refund/${refundRequestId}`);
    if (!res.ok) return undefined;
    return (await res.json()) as RefundRequest | null;
  } catch {
    return undefined;
  }
}

// GET /return_refund/by_order/{order_id}. The agent keeps one request per order, so at most one is expected;
// if several exist (older data) the newest one wins. undefined when the call failed.
export async function fetchRefundRequestForOrder(orderId: number): Promise<RefundRequest | null | undefined> {
  try {
    const res = await fetch(`${API_URL}/support/return_refund/by_order/${orderId}`);
    if (!res.ok) return undefined;
    const list = (await res.json()) as RefundRequest[];
    if (!Array.isArray(list) || list.length === 0) return null;
    return list.reduce((a, b) => (b.refund_request_id > a.refund_request_id ? b : a));
  } catch {
    return undefined;
  }
}
