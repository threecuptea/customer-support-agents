"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Send,
  Loader2,
  LogOut,
  PackageSearch,
  User,
  Bot,
  MessageCircleQuestion,
} from "lucide-react";
import { useAuth, useRequireRole } from "../../../lib/auth-context";

// Backend API base URL — defaults to same-origin (single-container deploy).
// Override with NEXT_PUBLIC_API_URL at build time for other setups.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

interface Exchange {
  question: string;
  answer: string;
}

interface GeneralSupportResponse {
  thread_id: string;
  general_inquiry: string;
  response: string;
}

export default function GeneralInquiryPage() {
  const { session, isLoading } = useRequireRole("customer");
  const { logout } = useAuth();
  const router = useRouter();

  const [question, setQuestion] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isLoading || !session) return null;

  const customer = session.customer_context;
  const greetingName = customer ? `${customer.title} ${customer.last_name}` : "there";
  const hasAnswer = exchanges.length > 0;

  const exit = () => {
    logout();
    router.push("/");
  };

  const askQuestion = async () => {
    const trimmed = question.trim();
    if (!trimmed || !customer) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/support/general`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          customer_context: customer,
          general_inquiry: trimmed,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GeneralSupportResponse = await res.json();
      setThreadId(data.thread_id);
      setExchanges((prev) => [...prev, { question: trimmed, answer: data.response }]);
      setQuestion("");
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
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
          >
            <LogOut className="w-4 h-4" /> Exit
          </button>
        </div>

        <h1 className="text-2xl font-bold text-brand-navy flex items-center gap-2 mb-2">
          <MessageCircleQuestion className="w-6 h-6 text-brand-purple" /> Ask us anything
        </h1>
        <p className="text-brand-gray text-sm mb-6">
          Hi {greetingName}, I will try my best to find an answer for you based
          upon our company policy. I will escalate to a human agent and
          somebody will contact you within 3 business days if I cannot have
          an answer. Let me know what your question is.
        </p>

        {exchanges.length > 0 && (
          <div className="space-y-4 mb-6">
            {exchanges.map((exchange, i) => (
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
          </div>
        )}

        {error && (
          <div className="mb-6 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
            {error}
          </div>
        )}

        <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-4 mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {hasAnswer ? "Ask another question?" : "What is your question?"}
          </label>
          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && askQuestion()}
              disabled={loading}
              placeholder="e.g. What is your return policy?"
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:bg-gray-50"
            />
            <button
              onClick={askQuestion}
              disabled={loading || !question.trim()}
              className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
              {hasAnswer ? "Ask another question?" : "Request an answer"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap justify-center gap-3">
          <button
            onClick={() => router.push("/customer/order-inquiry")}
            className="inline-flex items-center gap-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            <PackageSearch className="w-4 h-4" /> Go to order inquiry
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
