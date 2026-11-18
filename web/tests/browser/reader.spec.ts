import { test, expect } from "@playwright/test";
test("scan selection, zoom/pan, name search, and multi-generation navigation", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "이 페이지의 인물" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "001.png 족보 원본 스캔" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "1. 測試甲 선택", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "測試甲", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("司直", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "확대", exact: true }).click();
  const viewport = page.locator(".scan-viewport");
  const bounds = await viewport.boundingBox();
  await page.mouse.move(bounds!.x + 15, bounds!.y + 70);
  await page.mouse.down();
  await page.mouse.move(bounds!.x + 70, bounds!.y + 110);
  await page.mouse.up();
  await expect(
    page.getByRole("heading", { name: "測試甲", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "선조 · 후손" }).click();
  await expect(
    page.getByRole("button", { name: "測試乙 후손 펼치기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "測試乙 후손 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "測試丁 후손 펼치기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "測試丁 후손 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "測試戊 후손 펼치기" }),
  ).toBeVisible();
  await page.locator(".tree-name").filter({ hasText: "測試丁" }).click();
  await expect(
    page.getByRole("img", { name: "002.png 족보 원본 스캔" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "선조 찾아가기", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "測試乙 선조 펼치기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "測試乙 선조 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "測試甲 선조 펼치기" }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "인물 이름 검색" }).fill("測試甲");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /測試甲.*001.png/ }).click();
  await expect(
    page.getByRole("img", { name: "001.png 족보 원본 스캔" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "測試甲", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/jokbo-reader-desktop.png",
    fullPage: true,
  });
});
test("mobile scan overlays and ROI coordinates remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: /003쪽/ }).click();
  const overlay = page.getByRole("button", { name: /偏移 선택/ });
  await expect(overlay).toBeVisible();
  expect(await overlay.evaluate((el) => (el as HTMLElement).style.left)).toBe(
    "10%",
  );
  await overlay.click();
  await expect(
    page.getByRole("heading", { name: "偏移", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "/tmp/jokbo-reader-mobile.png",
    fullPage: true,
  });
});
