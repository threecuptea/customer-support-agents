"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Mirrors backend/models/model.py — OrderItem, Order, CustomerContext, AuthResponse.

export interface OrderItem {
  product_id: string;
  product_name: string;
  supplier_name: string;
  unit_price: number;
  number_units: number;
  non_refundable: boolean;
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
  customer_context: CustomerContext | null;
}

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
  login: (response: AuthResponse) => void;
  logout: () => void;
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

  const login = (response: AuthResponse) => {
    const next: AuthSession = {
      email_addr: response.email_addr,
      role: response.role,
      customer_context: response.customer_context,
    };
    setSession(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const logout = () => {
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
