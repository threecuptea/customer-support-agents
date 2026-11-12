"use client";

import { useCallback, useEffect, useRef } from "react";
import { useOrderInquiry } from "./order-inquiry-context";
import { fetchRefundRequest, WAITING_FOR_REVIEW } from "./refund-request";

// How often to re-read a request that is waiting for a human review while the screen is open. Reviews take
// minutes, so this is a light poll; it stops by itself as soon as the status changes.
export const REFUND_POLL_INTERVAL_MS = 20_000;

// Keeps the shared refund request in step with Redis (CSA-23). Pull only, no push: updates can only happen to a
// request waiting for a review, and a customer who has left gets an email instead. Triggers:
//   - refresh(): the caller invokes it on events (opening chat, after a chat reply);
//   - the window regaining focus / the tab becoming visible again;
//   - a light poll while the status is `wait_for_manual_review`.
// A null/failed read keeps the last known state (a Redis wipe must not blank the screen).
export function useRefundRequestSync() {
  const { refundRequest, setRefundRequest } = useOrderInquiry();
  const id = refundRequest?.refund_request_id ?? null;
  const status = refundRequest?.status ?? null;

  // Returning to the tab fires BOTH `focus` and `visibilitychange`; a read already in flight answers both.
  const inFlight = useRef(false);
  const refresh = useCallback(async () => {
    if (id == null || inFlight.current) return;
    inFlight.current = true;
    try {
      const fresh = await fetchRefundRequest(id);
      if (fresh) setRefundRequest(fresh);
    } finally {
      inFlight.current = false;
    }
  }, [id, setRefundRequest]);

  useEffect(() => {
    if (id == null) return;
    const onVisible = () => {
      // Only a request waiting for a review can change behind our back; skip the pull for any other status.
      if (document.visibilityState === "visible" && status === WAITING_FOR_REVIEW) void refresh();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [id, status, refresh]);

  useEffect(() => {
    if (id == null || status !== WAITING_FOR_REVIEW) return;
    const timer = setInterval(() => void refresh(), REFUND_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [id, status, refresh]);

  return { refresh };
}
