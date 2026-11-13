"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { Order } from "./auth-context";
import { RefundRequest } from "./refund-request";

// Backend API base URL — defaults to same-origin (single-container deploy).
// Override with NEXT_PUBLIC_API_URL at build time for other setups.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// Scoped to the /customer/order-inquiry/* route tree via layout.tsx, so it lives
// in a React context rather than localStorage: order-inquiry/page.tsx (CSA-11,
// select + chat) and order-inquiry/return/page.tsx (CSA-14/15/16, survey +
// policy + itemized return) are deliberately separate components — return/refund
// is a heavy enough topic to deserve its own file — but both need the same
// thread_id and target_order. A layout wrapping both with this provider keeps
// that state alive across navigation between them without passing it through
// the URL or re-fetching it.
interface ExchangeReturnSurvey {
  done: boolean;
  reasonKey: string | null;
  otherText: string;
  recommendation: string | null;
  // Set by /exchange_return/recommend for damaged/defective/wrong-item reasons: these go through
  // special handling (photo proof, CSR review), never the normal return/refund channel.
  specialExchangeHandling: boolean;
}

const EMPTY_SURVEY: ExchangeReturnSurvey = {
  done: false,
  reasonKey: null,
  otherText: "",
  recommendation: null,
  specialExchangeHandling: false,
};

// A turn in the order-detail chat transcript (CSA-11). Lives here rather than
// in page.tsx's own state so it survives a round-trip through the return/refund
// screen: both are routes under the same layout, so page.tsx unmounts and
// remounts when the customer navigates to/from .../return, which would
// otherwise silently blank out an in-progress conversation even though the
// backend thread itself is untouched.
export interface Exchange {
  question: string | null; // null for the deterministic first reply from /order/init
  answer: string;
}

interface OrderInquiryContextValue {
  threadId: string | null;
  setThreadId: (id: string | null) => void;
  targetOrder: Order | null;
  setTargetOrder: (order: Order | null) => void;
  exchanges: Exchange[];
  setExchanges: React.Dispatch<React.SetStateAction<Exchange[]>>;

  // The order's refund request (CSA-23), shared by the order chat screen (card) and the return screen so a
  // status changed by a Slack review shows on both. Cleared by resetForNewOrder().
  refundRequest: RefundRequest | null;
  setRefundRequest: (rr: RefundRequest | null) => void;
  // True once the opening reply of the order chat was produced knowing the order's refund request. A request created
  // later (on the return screen) makes the seeded static reply stale; the order screen then re-asks /order/init.
  greetingKnowsRequest: boolean;
  setGreetingKnowsRequest: (known: boolean) => void;

  // Exchange/return survey (CSA-14) completion for the current order — lets the
  // customer revisit the survey screen within this visit and press "Start
  // return for refund process" to bypass re-filling it, per the ticket's own
  // "if you revisit ... you can press ... to bypass" wording. Scoped per-order:
  // resetForNewOrder() clears it when the customer picks a different order.
  exchangeReturnSurvey: ExchangeReturnSurvey;
  markExchangeReturnSurveyDone: (
    reasonKey: string,
    otherText: string,
    recommendation: string,
    specialExchangeHandling?: boolean
  ) => void;

  // Clears target_order, the chat transcript, and the survey state above, but
  // keeps thread_id — used by "Back to order selection" since the running
  // conversation summary should still span both orders within one visit (see
  // CSA-11's own notes on this).
  resetForNewOrder: () => void;

  // Best-effort: tells the backend to summarize this order thread before it's
  // abandoned (Exit, or navigating to a different support flow entirely).
  // Never blocks the caller on failure.
  leaveOrderThread: () => Promise<void>;
}

const OrderInquiryContext = createContext<OrderInquiryContextValue | null>(null);

interface OrderInquiryProviderProps {
  children: React.ReactNode;
  // Seed values, used only by tests (renderWithOrderInquiry in test-utils.tsx)
  // to put the provider directly into an "already on order X" state without
  // racing a setup effect against the page's own mount-time guard effect.
  // Real usage (layout.tsx) never passes these — the provider always starts
  // empty and gets populated by the order-inquiry page itself.
  initialThreadId?: string | null;
  initialTargetOrder?: Order | null;
  initialRefundRequest?: RefundRequest | null;
  initialExchanges?: Exchange[];
}

export function OrderInquiryProvider({
  children,
  initialThreadId = null,
  initialTargetOrder = null,
  initialRefundRequest = null,
  initialExchanges = [],
}: OrderInquiryProviderProps) {
  const [threadId, setThreadId] = useState<string | null>(initialThreadId);
  const [targetOrder, setTargetOrder] = useState<Order | null>(initialTargetOrder);
  const [exchanges, setExchanges] = useState<Exchange[]>(initialExchanges);
  const [refundRequest, setRefundRequest] = useState<RefundRequest | null>(initialRefundRequest);
  const [greetingKnowsRequest, setGreetingKnowsRequest] = useState(false);
  const [exchangeReturnSurvey, setExchangeReturnSurvey] = useState<ExchangeReturnSurvey>(EMPTY_SURVEY);

  const markExchangeReturnSurveyDone = useCallback(
    (reasonKey: string, otherText: string, recommendation: string, specialExchangeHandling = false) => {
      setExchangeReturnSurvey({ done: true, reasonKey, otherText, recommendation, specialExchangeHandling });
    },
    []
  );

  const resetForNewOrder = useCallback(() => {
    setTargetOrder(null);
    setExchanges([]);
    setRefundRequest(null);
    setGreetingKnowsRequest(false);
    setExchangeReturnSurvey(EMPTY_SURVEY);
  }, []);

  const leaveOrderThread = useCallback(async () => {
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
  }, [threadId]);

  return (
    <OrderInquiryContext.Provider
      value={{
        threadId,
        setThreadId,
        targetOrder,
        setTargetOrder,
        exchanges,
        setExchanges,
        refundRequest,
        setRefundRequest,
        greetingKnowsRequest,
        setGreetingKnowsRequest,
        exchangeReturnSurvey,
        markExchangeReturnSurveyDone,
        resetForNewOrder,
        leaveOrderThread,
      }}
    >
      {children}
    </OrderInquiryContext.Provider>
  );
}

export function useOrderInquiry() {
  const ctx = useContext(OrderInquiryContext);
  if (!ctx) throw new Error("useOrderInquiry must be used within OrderInquiryProvider");
  return ctx;
}
