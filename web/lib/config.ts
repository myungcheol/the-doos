import { config } from "dotenv";
import path from "node:path";

// Python and Next.js share the root .env. Explicit process variables win.
export const projectRoot = path.resolve(
  /* turbopackIgnore: true */ process.env.JOKBO_PROJECT_ROOT || "..",
);
config({
  path: path.join(/* turbopackIgnore: true */ projectRoot, ".env"),
  quiet: true,
});
export function databaseUrl() {
  const url =
    process.env.JOKBO_WEB_DATABASE_URL ||
    process.env.DATABASE_URL ||
    process.env.JOKBO_DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is required");
  return url;
}
export function assetRoot() {
  const root = process.env.JOKBO_ASSET_ROOT;
  if (!root) throw new Error("JOKBO_ASSET_ROOT is required");
  return path.resolve(projectRoot, root);
}
export function publicEditions(): string[] | null {
  const ids = (process.env.JOKBO_PUBLIC_EDITIONS || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  return ids.length ? ids : null;
}
