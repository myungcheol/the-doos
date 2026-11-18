import { NextRequest, NextResponse } from "next/server";
import * as catalog from "@/lib/catalog";
import {
  HttpError,
  offset,
  pageId,
  personId,
  required,
} from "@/lib/validation";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ route: string[] }> },
) {
  try {
    const { route } = await context.params;
    const q = request.nextUrl.searchParams;
    let result: unknown;
    if (route.join("/") === "editions") result = await catalog.editions();
    else if (route.join("/") === "pages")
      result = await catalog.pages(
        required(q.get("edition")),
        offset(q.get("offset")),
        (q.get("q") || "").slice(0, 100),
      );
    else if (route[0] === "pages" && route.length === 2)
      result = await catalog.page(pageId(route[1]));
    else if (
      route[0] === "pages" &&
      route[2] === "image" &&
      route.length === 3
    ) {
      const buffer = await catalog.pageImage(pageId(route[1]));
      return new Response(new Uint8Array(buffer), {
        headers: {
          "Content-Type": "image/jpeg",
          "Cache-Control": "private, no-cache",
        },
      });
    } else if (route.join("/") === "people") {
      const query = (q.get("q") || "").trim();
      if (!query || query.length > 80)
        throw new HttpError(400, "이름을 1~80자로 입력하세요.");
      const match = q.get("match") || "contains";
      if (!["exact", "prefix", "contains"].includes(match))
        throw new HttpError(400, "검색 방식이 올바르지 않습니다.");
      result = await catalog.search(
        required(q.get("edition")),
        query,
        offset(q.get("offset")),
        match,
      );
    } else if (route[0] === "people" && route.length === 2)
      result = await catalog.detail(
        required(q.get("edition")),
        personId(route[1]),
      );
    else if (
      route[0] === "people" &&
      route[2] === "relatives" &&
      route.length === 3
    ) {
      const direction = q.get("direction") || "descendants";
      if (direction !== "ancestors" && direction !== "descendants")
        throw new HttpError(400, "탐색 방향이 올바르지 않습니다.");
      result = await catalog.relatives(
        required(q.get("edition")),
        personId(route[1]),
        direction,
        offset(q.get("offset")),
      );
    } else throw new HttpError(404, "요청한 정보를 찾을 수 없습니다.");
    return NextResponse.json(result, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof HttpError)
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    console.error("Reader request failed", {
      type: error instanceof Error ? error.name : "unknown",
    });
    return NextResponse.json(
      { error: "자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요." },
      { status: 503 },
    );
  }
}
