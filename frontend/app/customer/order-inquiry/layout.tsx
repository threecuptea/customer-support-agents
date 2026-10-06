import { OrderInquiryProvider } from "../../../lib/order-inquiry-context";

// Scopes OrderInquiryProvider to this route subtree so page.tsx (CSA-11,
// select + chat) and return/page.tsx (CSA-14/15/16, survey + policy + itemized
// return) share one thread_id/target_order without either page re-fetching or
// serializing it through the URL. See lib/order-inquiry-context.tsx.
export default function OrderInquiryLayout({ children }: { children: React.ReactNode }) {
  return <OrderInquiryProvider>{children}</OrderInquiryProvider>;
}
