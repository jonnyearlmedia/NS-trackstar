import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";
const NAPA_PIPE_ID = "8e169a83-82da-4251-bd8e-47907990ffe8";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/admin/location-debug/${NAPA_PIPE_ID}`, { cache: "no-store" });
    const text = await response.text();
    let payload: unknown = text;
    try {
      payload = JSON.parse(text);
    } catch {
      // Keep bounded text if the diagnostic endpoint itself fails unexpectedly.
      payload = text.slice(0, 1000);
    }
    return NextResponse.json({ ok: response.ok, status: response.status, payload }, { status: response.ok ? 200 : 502 });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "location probe failed" },
      { status: 502 },
    );
  }
}
