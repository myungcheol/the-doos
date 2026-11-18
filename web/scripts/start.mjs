import { cp } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
process.env.JOKBO_PROJECT_ROOT ||= path.resolve(webRoot, "..");
process.env.HOSTNAME = process.env.JOKBO_WEB_HOST || "127.0.0.1";
await cp(
  path.join(webRoot, ".next/static"),
  path.join(webRoot, ".next/standalone/.next/static"),
  { recursive: true },
);
await cp(
  path.join(webRoot, "public"),
  path.join(webRoot, ".next/standalone/public"),
  { recursive: true },
);
await import(path.join(webRoot, ".next/standalone/server.js"));
