import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";
const ONE_LAKE_ID = "b4d202ca-d7c1-4518-8a39-0e61ac967363";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [briefingResponse, contextResponse] = await Promise.all([
      fetch(`${API_BASE}/briefing?window=week&limit=3`, { cache: "no-store" }),
      fetch(`${API_BASE}/projects/${ONE_LAKE_ID}/context`, { cache: "no-store" }),
    ]);

    const briefingText = await briefingResponse.text();
    const contextText = await contextResponse.text();
    const parse = (text: string) => {
      try {
        return JSON.parse(text) as unknown;
      } catch {
        return text.slice(0, 500);
      }
    };

    return NextResponse.json(
      {
        ok: briefingResponse.ok && contextResponse.ok,
        briefing_status: briefingResponse.status,
        context_status: contextResponse.status,
        briefing: parse(briefingText),
        context: parse(contextText),
        checked_at: new Date().toISOString(),
      },
      { status: briefingResponse.ok && contextResponse.ok ? 200 : 502 },
    );
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "product probe failed" },
      { status: 502 },
    );
  }
}
