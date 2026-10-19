"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Mirrors backend/models — OrderItem, Order, CustomerContext (customer_support_model.py), AuthResponse (auth_model.py).

export interface OrderItem {
  product_id: string;
  product_name: string;
  supplier_name: string;
  unit_price: number;
  number_units: number;
  nonrefundable_item: boolean;
  nonrefundable_reason: "intimate item" | "luxury goods" | null;
}

export interface Order {
  order_id: number;
  order_date: string;
  total_amount_incl_tax: number;
  tax_applied_rate: number;
  status: "delivered" | "transit" | "pending";
  notes: string | null;
  ship_date: string | null;
  estimated_delivery_date: string | null;
  tracking_number: string | null;
  delivery_date: string | null;
  items: OrderItem[];
}

export interface CustomerContext {
  customer_id: number;
  title: "Mr." | "Ms." | "Mrs." | "Dr." | "Mx.";
  first_name: string;
  last_name: string;
  email: string;
  latest_orders: Order[];
}

export interface AuthResponse {
  email_addr: string;
  is_auth: boolean;
  role: "csr" | "customer";
}

// POST /api/auth returns a 2-element array: [AuthResponse, CustomerContext | null].
export type AuthApiResult = [AuthResponse, CustomerContext | null];

// Session is only ever constructed from an AuthResponse once is_auth === true.
export interface AuthSession {
  email_addr: string;
  role: "csr" | "customer";
  customer_context: CustomerContext | null;
}

const STORAGE_KEY = "csa_session";

interface AuthContextValue {
  session: AuthSession | null;
  isLoading: boolean;
  login: (response: AuthResponse, customerContext: CustomerContext | null) => void;
  logout: () => void;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// RBAC (CSA-21): the backend answers 401 when the server-side session has no role
// (never signed in, cookie expired/cleared, secret key changed) and 403 when the role
// doesn't match the endpoint. Either way the locally stored session (localStorage) no
// longer matches the server, so drop it and go back to the login page. Handled here once
// by wrapping window.fetch for /api calls rather than at every call site.
// /auth itself is excluded: a failed login is handled by the login page.
export function isSessionRejection(url: string, status: number) {
  if (status !== 401 && status !== 403) return false;
  if (!url.startsWith(API_URL) && !url.includes("/api/")) return false;
  return !/\/auth(\/|\?|$)/.test(url);
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setSession(JSON.parse(raw));
    } catch {
      // corrupt/stale localStorage — treat as logged out
    } finally {
      setIsLoading(false);
    }
  }, []);

  const router = useRouter();

  useEffect(() => {
    const originalFetch = window.fetch;
    window.fetch = async (input, init) => {
      const res = await originalFetch(input, init);
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (isSessionRejection(url, res.status)) {
        setSession(null);
        try {
          localStorage.removeItem(STORAGE_KEY);
        } catch {
          // ignore
        }
        router.replace("/");
      }
      return res;
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, [router]);

  const login = (response: AuthResponse, customerContext: CustomerContext | null) => {
    const next: AuthSession = {
      email_addr: response.email_addr,
      role: response.role,
      customer_context: customerContext,
    };
    setSession(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const logout = () => {
    // Best-effort: also drop the server-side session cookie's role.
    fetch(`${API_URL}/auth/logout`, { method: "POST" }).catch(() => {});
    setSession(null);
    localStorage.removeItem(STORAGE_KEY);
  };

  return (
    <AuthContext.Provider value={{ session, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

// Redirects to "/" if there's no session, or the session's role doesn't match.
// Returns `session: null` whenever the page isn't authorized to render (including
// a role mismatch), so callers only ever need `if (isLoading || !session) return null;`
// — no need to separately re-check `session.role` at each call site.
export function useRequireRole(role: "csr" | "customer") {
  const { session, isLoading } = useAuth();
  const router = useRouter();
  const authorized = !!session && session.role === role;

  useEffect(() => {
    if (!isLoading && !authorized) {
      router.replace("/");
    }
  }, [isLoading, authorized, router]);

  return { session: authorized ? session : null, isLoading };
}
