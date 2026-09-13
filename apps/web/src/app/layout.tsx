import type { Metadata, Viewport } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import "./ux-polish.css";
import "./final-device.css";
import "./visual-refresh.css";
import "./editorial-polish.css";
import "./interaction-polish.css";
import "./content-polish.css";
import "./map-hierarchy-polish.css";

import { PwaBootstrap } from "@/components/pwa-bootstrap";

export const metadata: Metadata = {
  title: "NS Trackstar",
  description: "Napa–Solano local development and infrastructure intelligence.",
  applicationName: "NS Trackstar",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/trackstar-icon.svg" },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Trackstar",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#eef5f7",
  colorScheme: "light",
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
