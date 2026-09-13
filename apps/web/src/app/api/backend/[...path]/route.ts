import { NextRequest } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const ALLOWED_PREFIXES = [
  "map/",
  "projects/",
  "search/projects/classified",
  "area/changes/public",
];

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const relativePath = path.join("/");
  if (!ALLOWED_PREFIXES.some((prefix) => relativePath === prefix || relativePath.startsWith(prefix))) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const upstream = new URL(`${BACKEND.replace(/\/$/, "")}/${relativePath}`);
  request.nextUrl.searchParams.forEach((value, key) => upstream.searchParams.append(key, value));

  try {
    const response = await fetch(upstream, {
      method: "GET",
      headers: { accept: "application/json" },
      cache: "no-store",
      signal: request.signal,
    });
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store, max-age=0",
      },
    });
  } catch {
    return Response.json({ detail: "Trackstar data service unavailable" }, { status: 502 });
  }
}
