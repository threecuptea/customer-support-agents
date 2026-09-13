"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft, Construction } from "lucide-react";
import { useRequireRole } from "../../../lib/auth-context";

export default function OrderInquiryPlaceholderPage() {
  const { session, isLoading } = useRequireRole("customer");
  const router = useRouter();

  if (isLoading || !session) return null;

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 flex items-center justify-center px-4 py-10">
      <div className="max-w-md w-full text-center bg-white border border-gray-100 rounded-xl shadow-soft p-8">
        <Construction className="w-10 h-10 text-brand-purple mx-auto mb-3" />
        <h1 className="text-xl font-bold text-brand-navy mb-2">
          Order inquiry &amp; return refund
        </h1>
        <p className="text-brand-gray text-sm mb-6">
          This is coming soon. We&apos;re still building order lookup and
          return/refund requests.
        </p>
        <button
          onClick={() => router.push("/customer")}
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
      </div>
    </main>
  );
}
