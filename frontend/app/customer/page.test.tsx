import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithAuth } from "../../lib/test-utils";
import CustomerSelectionsPage from "./page";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const customerSession = {
  email_addr: "cust@x.com",
  role: "customer" as const,
  customer_context: {
    customer_id: 1,
    title: "Ms." as const,
    first_name: "Ada",
    last_name: "Lovelace",
    email: "cust@x.com",
    latest_orders: [],
  },
};

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
});

describe("CustomerSelectionsPage", () => {
  it("redirects to / when there is no customer session", async () => {
    renderWithAuth(<CustomerSelectionsPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("greets the customer and lists all FAQ sections", async () => {
    renderWithAuth(<CustomerSelectionsPage />, { seedSession: customerSession });
    expect(await screen.findByText(/hi ms\. lovelace/i)).toBeInTheDocument();
    expect(screen.getByText("Shipping & Delivery")).toBeInTheDocument();
    expect(screen.getByText("Returns and Refunds")).toBeInTheDocument();
    expect(screen.getByText("Orders and Payment")).toBeInTheDocument();
  });

  it("navigates to the order-inquiry placeholder", async () => {
    renderWithAuth(<CustomerSelectionsPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);
    await userEvent.click(screen.getByRole("button", { name: /order inquiry & return refund/i }));
    expect(push).toHaveBeenCalledWith("/customer/order-inquiry");
  });

  it("navigates to the others placeholder", async () => {
    renderWithAuth(<CustomerSelectionsPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);
    await userEvent.click(screen.getByRole("button", { name: /^others$/i }));
    expect(push).toHaveBeenCalledWith("/customer/others");
  });

  it("clears the session and returns home on Exit", async () => {
    renderWithAuth(<CustomerSelectionsPage />, { seedSession: customerSession });
    await screen.findByText(/hi ms\. lovelace/i);
    await userEvent.click(screen.getAllByRole("button", { name: /exit/i })[0]);
    expect(push).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("csa_session")).toBeNull();
  });
});
