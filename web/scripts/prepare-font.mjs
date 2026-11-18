import { copyFile, mkdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const name = "NotoSansCJKkr-Regular.otf";
const source = path.resolve(webRoot, "../assets/fonts", name);
const targetDir = path.join(webRoot, "public/fonts");
const target = path.join(targetDir, name);
try {
  const [origin, existing] = await Promise.all([
    stat(source),
    stat(target).catch(() => null),
  ]);
  if (
    !existing ||
    origin.size !== existing.size ||
    origin.mtimeMs > existing.mtimeMs
  ) {
    await mkdir(targetDir, { recursive: true });
    await copyFile(source, target);
  }
} catch (error) {
  console.error("Bundled Korean/Hanja font is required:", source);
  throw error;
}
