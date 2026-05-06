import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Synapse — Observability",
  description: "Live multi-agent coordination dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-bg-base text-text-primary min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
