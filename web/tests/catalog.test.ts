import { test, after } from "node:test";
import assert from "node:assert/strict";
import { literalLike, offset, personId } from "../lib/validation";

test("query input treats SQL wildcard characters as literal text", () => {
  assert.equal(literalLike("a%b_c\\d"), "a\\%b\\_c\\\\d");
  assert.throws(() => offset("-1"));
  assert.throws(() => personId("' OR 1=1"));
});

const dsn = process.env.JOKBO_TEST_DATABASE_URL;
if (dsn) {
  process.env.JOKBO_WEB_DATABASE_URL = dsn;
  process.env.JOKBO_PUBLIC_EDITIONS = "web-test";
  process.env.JOKBO_ASSET_ROOT = process.env.JOKBO_WEB_TEST_ROOT
    ? `${process.env.JOKBO_WEB_TEST_ROOT}/assets`
    : "/tmp/jokbo-web-fixture/assets";
}
test(
  "public reader uses active sources, hides rejected data, preserves source coordinates, and traverses both directions",
  { skip: !dsn },
  async () => {
    const catalog = await import("../lib/catalog");
    const { pool } = await import("../lib/db");
    const uid = (n: number) =>
      `PER_${n.toString(16).toUpperCase().padStart(32, "0")}`;
    const editions = await catalog.editions();
    assert.deepEqual(
      editions.map((e) => e.id),
      ["web-test"],
    );
    const pages = await catalog.pages("web-test");
    assert.equal(pages.items.length, 3);
    await assert.rejects(() => catalog.pages("hidden-test"));
    const page = await catalog.page(pages.items[0].id);
    assert.equal(page.peopleList.length, 4);
    assert.equal(page.image?.width, 900);
    assert.equal(page.image?.offsetX, 0);
    const roi = await catalog.page(pages.items[2].id);
    assert.equal(roi.image?.offsetX, 100);
    assert.equal(roi.image?.offsetY, 200);
    assert.equal(roi.peopleList[0].bbox?.x, 120);
    assert.equal(roi.image?.width, 200);
    assert.equal((await catalog.search("web-test", "測試")).items.length, 5);
    assert.equal(
      (await catalog.search("web-test", "測試甲", 0, "exact")).items.length,
      1,
    );
    assert.equal((await catalog.search("web-test", "%")).items.length, 0);
    assert.equal(
      (await catalog.search("web-test", "' OR 1=1 --")).items.length,
      0,
    );
    assert.equal((await catalog.search("web-test", "拒絕")).items.length, 0);
    assert.deepEqual(
      (await catalog.relatives("web-test", uid(1), "descendants")).items.map(
        (p) => p.id,
      ),
      [uid(2), uid(3)],
    );
    assert.deepEqual(
      new Set(
        (await catalog.relatives("web-test", uid(4), "ancestors")).items.map(
          (p) => p.id,
        ),
      ),
      new Set([uid(2), uid(3)]),
    );
    assert.equal(
      (await catalog.relatives("web-test", uid(4), "descendants")).items[0].id,
      uid(5),
    );
    const detail = await catalog.detail("web-test", uid(1));
    assert.equal(detail.sources[0].fields.office_title, "司直");
    assert.equal(detail.partners[0].kind, "wife");
    assert.ok(!JSON.stringify(detail).includes("PRIVATE_NOTE_FOR_TEST"));
    assert.ok(!JSON.stringify(detail).includes("source_image"));
    await assert.rejects(() => catalog.detail("web-test", uid(6)));
    const bytes = await catalog.pageImage(pages.items[0].id);
    assert.equal(bytes[0], 0xff);
    const client = await pool().connect();
    try {
      await assert.rejects(
        () =>
          client.query(
            "UPDATE jokbo.editions SET revision=revision WHERE id='web-test'",
          ),
        /read-only/,
      );
    } finally {
      client.release();
    }
  },
);
after(async () => {
  if (dsn) {
    const { pool } = await import("../lib/db");
    await pool().end();
  }
});
