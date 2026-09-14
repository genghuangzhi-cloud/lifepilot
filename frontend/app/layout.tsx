import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "LifePilot · Adaptive planning agent", description: "An explainable personal execution system." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
