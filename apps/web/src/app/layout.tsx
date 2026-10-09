import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PharmaIntelligence | Pharmacy operations, in focus",
  description: "An intelligent workspace for pharmacy inventory, orders, procurement, and analytics.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
