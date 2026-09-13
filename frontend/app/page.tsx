"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, LogIn } from "lucide-react";
import { useAuth, AuthResponse } from "../lib/auth-context";
import { FAQ_SECTIONS } from "../lib/faq";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

function findQuestion(text: string) {
  for (const section of FAQ_SECTIONS) {
    const hit = section.entries.find((entry) => entry.question === text);
    if (hit) return hit.question;
  }
  return text;
}

// There's no logo, so a small scattered, hand-picked collage of FAQ questions
// stands in for one. Full FAQ list lives on /customer.
const FAQ_TEASERS = [
  { text: findQuestion("When will my order ship?"), className: "text-2xl sm:text-3xl font-bold text-blue-600 -rotate-6" },
  { text: findQuestion("What is your return policy?"), className: "text-sm sm:text-base font-semibold text-amber-500 -rotate-2 ml-10" },
  { text: findQuestion("How long does a delivery take?"), className: "text-lg sm:text-xl font-semibold text-teal-600 -rotate-3" },
  { text: findQuestion("What if my package is lost or late?"), className: "text-sm sm:text-base italic font-medium text-fuchsia-600 -rotate-1 ml-16" },
];

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
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-brand-blue/10 flex flex-col items-center px-4 py-12">
      <h1 className="text-3xl font-bold text-brand-navy text-center mt-4 mb-2">
        e-shopping.com
      </h1>
      <p className="text-brand-gray text-center text-sm">Customer Support</p>

      <div className="flex-1 min-h-8" />

      <div className="flex flex-col items-center">
        <div className="text-center space-y-4 mb-8">
          {FAQ_TEASERS.map(({ text, className }) => (
            <p key={text} className={className}>
              {text}
            </p>
          ))}
        </div>

        <div className="max-w-md w-full">
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
        </div>
      </div>

      <div className="flex-[2] min-h-8" />
    </main>
  );
}
