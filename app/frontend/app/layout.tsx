import type { Metadata } from "next";
import { AuthProvider } from "../lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Cost Doctor — Find where your AI budget is leaking",
  description:
    "Per-customer AI unit economics, margin-killer diagnosis, and dollar-quantified savings recommendations for B2B AI products.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
