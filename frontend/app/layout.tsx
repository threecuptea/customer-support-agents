import "./globals.css";
import { AuthProvider } from "../lib/auth-context";

export const metadata = {
  title: "e-shopping.com — Customer Support",
  description: "e-shopping.com customer support: order help, returns & refunds, and general FAQs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
