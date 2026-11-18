import type { PoolClient } from "pg";
import path from "node:path";
import fs from "node:fs/promises";
import sharp from "sharp";
import { read } from "./db";
import { assetRoot, publicEditions } from "./config";
import { HttpError, literalLike } from "./validation";
import type {
  Box,
  Edition,
  Listing,
  PageDetail,
  PageSummary,
  PersonDetail,
  PersonSummary,
  Relative,
  Status,
} from "./types";

type Row = Record<string, any>;
const visible = "o.status <> 'rejected' AND r.active";
const summarySql = `o.person_id, o.id, o.page_id::text, p.name AS page_name, o.name, o.status,
  o.reviewed->>'gender' AS gender, o.reviewed->>'generation_number' AS generation, o.source->'bbox' AS bbox`;
function box(value: unknown): Box | null {
  const b = value as Box;
  return b &&
    [b.x, b.y, b.width, b.height].every(Number.isFinite) &&
    b.width > 0 &&
    b.height > 0
    ? b
    : null;
}
function summary(r: Row): PersonSummary {
  return {
    id: r.person_id,
    occurrenceId: r.id,
    pageId: r.page_id,
    pageName: r.page_name,
    name: r.name || "이름 미판독",
    status: r.status,
    gender: r.gender || "unknown",
    generation:
      r.generation && Number.isFinite(Number(r.generation))
        ? Number(r.generation)
        : null,
    bbox: box(r.bbox),
  };
}
function listing<T>(items: T[], start: number, size: number): Listing<T> {
  return {
    items: items.slice(0, size),
    hasMore: items.length > size,
    nextOffset: start + Math.min(items.length, size),
  };
}
async function edition(c: PoolClient, id: string) {
  const result = await c.query(
    "SELECT id FROM jokbo.editions WHERE id=$1 AND ($2::text[] IS NULL OR id=ANY($2))",
    [id, publicEditions()],
  );
  if (!result.rowCount)
    throw new HttpError(404, "공개된 판본을 찾을 수 없습니다.");
}
async function person(c: PoolClient, eid: string, id: string) {
  const r = await c.query(
    `SELECT 1 FROM jokbo.occurrences o JOIN jokbo.ocr_runs r ON r.id=o.run_id
    WHERE o.edition_id=$1 AND o.person_id=$2 AND ${visible} LIMIT 1`,
    [eid, id],
  );
  if (!r.rowCount)
    throw new HttpError(404, "이 판본에서 인물을 찾을 수 없습니다.");
}
export async function editions(): Promise<Edition[]> {
  return read(async (c) =>
    (
      await c.query(
        `SELECT e.id, e.meta->>'publication_year' AS year, e.meta->>'volume' AS volume,
    (SELECT count(*)::int FROM jokbo.pages p JOIN jokbo.ocr_runs r ON r.page_id=p.id AND r.active WHERE p.edition_id=e.id) AS pages,
    (SELECT count(DISTINCT o.person_id)::int FROM jokbo.occurrences o JOIN jokbo.ocr_runs r ON r.id=o.run_id
      WHERE o.edition_id=e.id AND ${visible}) AS people
    FROM jokbo.editions e WHERE ($1::text[] IS NULL OR e.id=ANY($1)) ORDER BY e.id`,
        [publicEditions()],
      )
    ).rows.map((r) => ({ ...r, year: r.year ? Number(r.year) : null })),
  );
}
export async function pages(
  eid: string,
  start = 0,
  query = "",
): Promise<Listing<PageSummary>> {
  return read(async (c) => {
    await edition(c, eid);
    const rows = (
      await c.query(
        `SELECT p.id::text, p.name,
      (SELECT count(*)::int FROM jokbo.occurrences o WHERE o.page_id=p.id AND o.run_id=r.id AND o.status<>'rejected') AS people
      FROM jokbo.pages p JOIN jokbo.ocr_runs r ON r.page_id=p.id AND r.active
      WHERE p.edition_id=$1 AND p.name ILIKE $2
      ORDER BY length(p.name), p.name, p.id LIMIT 101 OFFSET $3`,
        [eid, `%${literalLike(query)}%`, start],
      )
    ).rows;
    return listing(rows, start, 100);
  });
}
async function pageRow(c: PoolClient, id: string) {
  const result = await c.query(
    `SELECT p.id::text, p.name, p.edition_id, r.id AS run_id,
    r.scan_id, r.roi_id, r.raw->'table_roi' AS roi
    FROM jokbo.pages p JOIN jokbo.ocr_runs r ON r.page_id=p.id AND r.active
    WHERE p.id=$1 AND ($2::text[] IS NULL OR p.edition_id=ANY($2))`,
    [id, publicEditions()],
  );
  if (!result.rowCount) throw new HttpError(404, "페이지를 찾을 수 없습니다.");
  return result.rows[0];
}
async function imageFile(row: Row) {
  const hash = row.scan_id || row.roi_id;
  if (!hash || !/^[a-f0-9]{64}$/.test(hash)) return null;
  const root = await fs.realpath(assetRoot());
  let filename: string;
  try {
    filename = await fs.realpath(path.join(root, hash.slice(0, 2), hash));
  } catch {
    throw new HttpError(404, "스캔 이미지 파일을 찾을 수 없습니다.");
  }
  if (!filename.startsWith(root + path.sep))
    throw new HttpError(404, "스캔 이미지를 찾을 수 없습니다.");
  return filename;
}
export async function page(id: string): Promise<PageDetail> {
  return read(async (c) => {
    const row = await pageRow(c, id);
    const people = (
      await c.query(
        `SELECT ${summarySql} FROM jokbo.occurrences o
      JOIN jokbo.pages p ON p.id=o.page_id JOIN jokbo.ocr_runs r ON r.id=o.run_id
      WHERE o.page_id=$1 AND ${visible} ORDER BY o.id`,
        [id],
      )
    ).rows.map(summary);
    people.sort(
      (a, b) =>
        (a.bbox?.y || 0) - (b.bbox?.y || 0) ||
        (b.bbox?.x || 0) - (a.bbox?.x || 0) ||
        a.occurrenceId.localeCompare(b.occurrenceId),
    );
    const filename = await imageFile(row);
    let image: PageDetail["image"] = null;
    if (filename) {
      const meta = await sharp(filename, {
        limitInputPixels: 180_000_000,
      }).metadata();
      image = {
        url: `/api/pages/${id}/image`,
        width: meta.width || 1,
        height: meta.height || 1,
        offsetX: row.scan_id ? 0 : Number(row.roi?.x || 0),
        offsetY: row.scan_id ? 0 : Number(row.roi?.y || 0),
        isRoi: !row.scan_id,
      };
    }
    return {
      id: row.id,
      name: row.name,
      edition: row.edition_id,
      people: people.length,
      peopleList: people,
      image,
    };
  });
}
export async function pageImage(id: string) {
  const row = await read((c) => pageRow(c, id));
  const filename = await imageFile(row);
  if (!filename) throw new HttpError(404, "스캔 이미지가 없습니다.");
  // Browser-compatible JPEG also supports TIFF/BMP input. No EXIF rotation:
  // stored boxes refer to the original pixel orientation.
  return sharp(filename, { limitInputPixels: 180_000_000 })
    .jpeg({ quality: 90 })
    .toBuffer();
}
export async function search(
  eid: string,
  query: string,
  start = 0,
  match = "contains",
): Promise<Listing<PersonSummary>> {
  return read(async (c) => {
    await edition(c, eid);
    const term = literalLike(query);
    const pattern =
      match === "exact" ? term : match === "prefix" ? `${term}%` : `%${term}%`;
    const rows = (
      await c.query(
        `SELECT ${summarySql} FROM jokbo.occurrences o JOIN jokbo.pages p ON p.id=o.page_id
      JOIN jokbo.ocr_runs r ON r.id=o.run_id WHERE o.edition_id=$1 AND ${visible} AND lower(o.name) LIKE lower($2)
      ORDER BY CASE WHEN o.name=$3 THEN 0 ELSE 1 END, o.name, length(p.name), p.name, o.id
      LIMIT 31 OFFSET $4`,
        [eid, pattern, query, start],
      )
    ).rows.map(summary);
    return listing(rows, start, 30);
  });
}
const fields = [
  "name_hanja",
  "sex_marker",
  "generation_number",
  "courtesy_name_hanja",
  "pen_name_hanja",
  "birth_text",
  "death_text",
  "office_title",
  "burial_text",
  "biography_text",
];
export async function detail(eid: string, id: string): Promise<PersonDetail> {
  return read(async (c) => {
    await edition(c, eid);
    await person(c, eid, id);
    const rows = (
      await c.query(
        `SELECT ${summarySql}, o.reviewed, o.raw->'name_ocr'->>'raw_text' AS raw_name
      FROM jokbo.occurrences o JOIN jokbo.pages p ON p.id=o.page_id JOIN jokbo.ocr_runs r ON r.id=o.run_id
      WHERE o.edition_id=$1 AND o.person_id=$2 AND ${visible} ORDER BY length(p.name), p.name, o.id`,
        [eid, id],
      )
    ).rows;
    const partners = (
      await c.query(
        `SELECT kind, status, record, partner_id FROM jokbo.partners
      WHERE edition_id=$1 AND person_id=$2 AND status<>'rejected' ORDER BY id`,
        [eid, id],
      )
    ).rows;
    return {
      id,
      sources: rows.map((r) => ({
        ...summary(r),
        rawName: r.raw_name || "",
        informationStatus: (r.reviewed.information_review_status === "confirmed"
          ? "confirmed"
          : "needs_review") as Status,
        fields: Object.fromEntries(
          fields.map((k) => [
            k,
            ["string", "number"].includes(typeof r.reviewed[k])
              ? r.reviewed[k]
              : null,
          ]),
        ),
      })),
      partners: partners.map((r) => ({
        kind: r.kind,
        status: r.status,
        personId: r.partner_id,
        name: String(
          r.record.name_and_record || r.record.name_text || "이름 미상",
        ),
      })),
    };
  });
}
export async function relatives(
  eid: string,
  id: string,
  direction: "ancestors" | "descendants",
  start = 0,
): Promise<Listing<Relative>> {
  return read(async (c) => {
    await edition(c, eid);
    await person(c, eid, id);
    // Only these constant column names are interpolated; all user input is bound.
    const [anchor, target] =
      direction === "ancestors"
        ? ["child_id", "parent_id"]
        : ["parent_id", "child_id"];
    const rows = (
      await c.query(
        `SELECT found.*, e.kind, e.id AS edge_id
      FROM jokbo.parent_child e CROSS JOIN LATERAL (
        SELECT ${summarySql} FROM jokbo.occurrences o JOIN jokbo.pages p ON p.id=o.page_id
        JOIN jokbo.ocr_runs r ON r.id=o.run_id
        WHERE o.person_id=e.${target} AND o.edition_id=e.edition_id AND ${visible}
        ORDER BY CASE WHEN o.status='confirmed' THEN 0 ELSE 1 END, length(p.name), p.name, o.id LIMIT 1
      ) found
      WHERE e.edition_id=$1 AND e.${anchor}=$2 AND e.status='confirmed'
      ORDER BY e.id, e.kind LIMIT 51 OFFSET $3`,
        [eid, id, start],
      )
    ).rows;
    return listing(
      rows.map((r) => ({ ...summary(r), kind: r.kind, edgeId: r.edge_id })),
      start,
      50,
    );
  });
}
