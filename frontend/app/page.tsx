"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, LogIn } from "lucide-react";
import { useAuth, AuthResponse } from "../lib/auth-context";
import { FAQ_SECTIONS } from "../lib/faq";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// A handful of questions (first couple per section) shown as decorative tags —
// there's no logo, so these stand in for one. Full FAQ list lives on /customer.
const FAQ_TEASERS = FAQ_SECTIONS.flatMap((section) =>
  section.entries.slice(0, 2).map((entry) => entry.question)
);

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { login } = useAuth();
  const router = useRouter();

  const submit = async () => {
    if (!email.trim()) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const res = await fetch(`${API_URL}/auth`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email_addr: email.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: AuthResponse = await res.json();
      if (!data.is_auth) {
        setNotFound(true);
        return;
      }
      login(data);
      router.push(data.role === "customer" ? "/customer" : "/csr");
    } catch (e) {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 flex items-center justify-center px-4 py-10">
      <div className="max-w-md w-full">
        <h1 className="text-3xl font-bold text-brand-navy text-center mb-1">
          e-shopping.com
        </h1>
        <p className="text-brand-gray text-center text-sm mb-6">
          Customer Support
        </p>

        <div className="bg-white border border-gray-100 rounded-xl shadow-soft p-5">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Sign in with your account email
          </label>
          <div className="flex gap-2">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="you@example.com"
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-purple/40"
            />
            <button
              onClick={submit}
              disabled={loading || !email.trim()}
              className="inline-flex items-center gap-1.5 bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <LogIn className="w-4 h-4" />
              )}
              Sign in
            </button>
          </div>

          {notFound && (
            <div className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
              We are unable to log you in because we are unable to find any
              customer with the login email, please double check it.
            </div>
          )}
          {error && (
            <div className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
              {error}
            </div>
          )}
        </div>

        <div className="mt-8">
          <p className="text-xs font-medium text-brand-gray text-center mb-3">
            Popular questions
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {FAQ_TEASERS.map((question) => (
              <span key={question} className="choice-badge">
                {question}
              </span>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
