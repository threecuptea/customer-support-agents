import { render } from "@testing-library/react";
import { AuthProvider, AuthSession, Order } from "./auth-context";
import { OrderInquiryProvider } from "./order-inquiry-context";

const STORAGE_KEY = "csa_session";

// Seeds localStorage with a session *before* mounting, so AuthProvider's
// hydration effect picks it up — mirrors how a real page load restores state.
export function renderWithAuth(
  ui: React.ReactElement,
  { seedSession }: { seedSession?: AuthSession } = {}
) {
  if (seedSession) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(seedSession));
  }
  return render(<AuthProvider>{ui}</AuthProvider>);
}

// Like renderWithAuth, but also wraps with OrderInquiryProvider — for the
// /customer/order-inquiry/* route tree, which in the real app gets this from
// layout.tsx (not rendered in these component-level tests). seedOrderInquiry
// puts the provider directly into an "already on order X" state, e.g. for
// testing return/page.tsx without going through page.tsx's own /order/init flow.
export function renderWithOrderInquiry(
  ui: React.ReactElement,
  {
    seedSession,
    seedOrderInquiry,
  }: { seedSession?: AuthSession; seedOrderInquiry?: { threadId: string; targetOrder: Order } } = {}
) {
  if (seedSession) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(seedSession));
  }
  return render(
    <AuthProvider>
      <OrderInquiryProvider
        initialThreadId={seedOrderInquiry?.threadId}
        initialTargetOrder={seedOrderInquiry?.targetOrder}
      >
        {ui}
      </OrderInquiryProvider>
    </AuthProvider>
  );
}

export function jsonResponse(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: async () => body } as Response;
}
