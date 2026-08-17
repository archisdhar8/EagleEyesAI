import type { Metadata } from "next";
import "./globals.css";
import "./research-depth.css";

export const metadata: Metadata = {
  title: "EagleEyes — Investment Decision System",
  description: "Evidence-grounded research, portfolio analysis, and persistent investment decision support.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
