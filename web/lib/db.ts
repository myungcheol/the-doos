import pg from "pg";
import { databaseUrl } from "./config";

const globalDb = globalThis as unknown as { jokboPool?: pg.Pool };
export function pool() {
  if (!globalDb.jokboPool) {
    globalDb.jokboPool = new pg.Pool({
      connectionString: databaseUrl(),
      max: 8,
      connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 30000,
      options: "-c default_transaction_read_only=on -c statement_timeout=8000",
    });
    globalDb.jokboPool.on("error", () =>
      console.error("PostgreSQL idle connection failed"),
    );
  }
  return globalDb.jokboPool;
}
export async function read<T>(
  fn: (client: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool().connect();
  try {
    await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    const value = await fn(client);
    await client.query("COMMIT");
    return value;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
