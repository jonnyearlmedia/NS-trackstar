import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import "./ux-polish.css";

import { PwaBootstrap } from "@/components/pwa-bootstrap";

export const metadata: Metadata = {
  title: "NS Trackstar",
  description: "Napa–Solano local development and infrastructure intelligence.",
  applicationName: "NS Trackstar",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/trackstar-icon.svg" },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Trackstar",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        <PwaBootstrap />
      </body>
    </html>
  );
}
