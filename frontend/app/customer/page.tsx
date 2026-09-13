"use client";

import { useRouter } from "next/navigation";
import { PackageSearch, MessageCircleQuestion, LogOut } from "lucide-react";
import { useAuth, useRequireRole } from "../../lib/auth-context";
import { FAQ_SECTIONS } from "../../lib/faq";

export default function CustomerSelectionsPage() {
  const { session, isLoading } = useRequireRole("customer");
  const { logout } = useAuth();
  const router = useRouter();

  if (isLoading || !session) return null;

  const customer = session.customer_context;
  const greetingName = customer ? `${customer.title} ${customer.last_name}` : "there";

  const exit = () => {
    logout();
    router.push("/");
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 py-10 px-4">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <span className="text-sm font-semibold text-brand-navy">e-shopping.com</span>
          <button
            onClick={exit}
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
          >
            <LogOut className="w-4 h-4" /> Exit
          </button>
        </div>

        <h1 className="text-2xl font-bold text-brand-navy mb-2">
          Hi {greetingName}, how can we help?
        </h1>
        <p className="text-brand-gray text-sm mb-6">
          If you are looking for e-shopping.com&apos;s policy, have a look at the
          FAQs below covering Shipping &amp; Delivery, Returns and Refunds, and
          Orders and Payment. If you&apos;ve already found your answer, press{" "}
          <strong>Exit</strong>. If you still have questions about a recent
          order, press <strong>Order inquiry &amp; return refund</strong>;
          otherwise press <strong>Others</strong>.
        </p>

        <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-5 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {FAQ_SECTIONS.map((section) => (
              <div key={section.title}>
                <h2 className="text-base font-bold text-brand-navy mb-3">
                  {section.title}
                </h2>
                <div className="space-y-4">
                  {section.entries.map((entry) => (
                    <div key={entry.question}>
                      <p className="text-sm font-medium text-gray-800 break-words">
                        Q: {entry.question}
                      </p>
                      <p className="text-sm text-brand-gray mt-0.5 break-words">
                        A: {entry.answer}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap justify-center gap-3">
          <button
            onClick={() => router.push("/customer/order-inquiry")}
            className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            <PackageSearch className="w-4 h-4" /> Order inquiry &amp; return refund
          </button>
          <button
            onClick={() => router.push("/customer/others")}
            className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            <MessageCircleQuestion className="w-4 h-4" /> Others
          </button>
          <button
            onClick={exit}
            className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            <LogOut className="w-4 h-4" /> Exit
          </button>
        </div>
      </div>
    </main>
  );
}
