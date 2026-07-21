import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SwarmDeck",
  description: "Agent-execution work management — tickets that do themselves, with evidence.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
