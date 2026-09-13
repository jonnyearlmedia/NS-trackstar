import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/admin/sources/cadence?days=7`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return NextResponse.json(
        {
          ok: false,
          backend_status: response.status,
          reason: "source cadence audit endpoint unavailable",
        },
        { status: 502 },
      );
    }

    const payload = await response.json();
    return NextResponse.json({ ok: true, ...payload });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        reason: error instanceof Error ? error.message : "source cadence audit failed",
      },
      { status: 502 },
    );
  }
}
