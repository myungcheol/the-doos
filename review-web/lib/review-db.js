import {readFileSync} from 'node:fs';
import {parseEnv} from 'node:util';
import path from 'node:path';
import pg from 'pg';

let pool;
export function reviewDB() {
  if (pool) return pool;
  let config = {};
  if (!process.env.PGDATABASE) {
    const env = {...parseEnv(readFileSync(path.resolve(process.cwd(), '../.env'), 'utf8')), ...process.env};
    config = {host:'127.0.0.1', port:Number(env.POSTGRES_PORT || 5432), database:env.POSTGRES_DB,
      user:env.POSTGRES_USER, password:env.POSTGRES_PASSWORD};
  }
  pool = new pg.Pool({...config, max:4, connectionTimeoutMillis:4000});
  pool.on('error', error => console.error('PostgreSQL connection error', error.code));
  return pool;
}
