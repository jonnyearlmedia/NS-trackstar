import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "NS Trackstar",
    short_name: "Trackstar",
    description: "Source-backed change intelligence for Napa and Solano Counties.",
    start_url: "/",
    display: "standalone",
    background_color: "#080b0d",
    theme_color: "#080b0d",
    orientation: "portrait-primary",
    icons: [
      {
        src: "/trackstar-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/trackstar-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
