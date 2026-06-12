import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { AuthGate } from "@/components/auth-gate";
import { AuthProvider } from "@/components/auth-provider";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Admin Portal",
  description: "Tenant, product, and billing administration for CoreAdmin.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <AuthProvider>
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}