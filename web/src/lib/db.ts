/**
 * the one place that knows how to talk to MySQL. every page and api route imports query() from here.
 *
 * it reads the same MYSQL_* settings as the pipeline, from web/.env.local (a symlink to the repo's
 * .env), so nothing about the database is hardcoded anywhere else. the web app only ever reads.
 *
 * usage (server components and route handlers only, never in the browser):
 *   import { query } from "@/lib/db";
 *
 *   type Artist = { id: number; name: string };
 *   const artists = await query<Artist>("SELECT id, name FROM artists WHERE id = ?", [12]);
 *   // -> [{ id: 12, name: "SZA" }]
 */

import mysql from "mysql2/promise";
import type { Pool, RowDataPacket } from "mysql2/promise";
import { connection } from "next/server";

// a few connections are plenty: every query here is a quick SELECT
const MAX_CONNECTIONS = 5;

// --- the connection pool ---

/**
 * opens the pool of connections. a pool keeps connections open between requests, so a page
 * doesn't pay for a new MySQL login every time it loads.
 */
function createPool(): Pool {
  return mysql.createPool({
    host: process.env.MYSQL_HOST,
    port: Number(process.env.MYSQL_PORT),
    user: process.env.MYSQL_USER,
    password: process.env.MYSQL_PASSWORD,
    database: process.env.MYSQL_DATABASE,
    // same as the pipeline: without this, "Beyoncé" comes back mangled
    charset: "utf8mb4",
    connectionLimit: MAX_CONNECTIONS,
  });
}

// in dev, every file save reloads this module. keeping the pool on globalThis means a reload
// reuses it instead of opening 5 more connections each time
const globalForDb = globalThis as unknown as { mysqlPool?: Pool };
const pool = globalForDb.mysqlPool ?? createPool();
if (process.env.NODE_ENV !== "production") {
  globalForDb.mysqlPool = pool;
}

// --- running a query ---

/**
 * runs one SELECT and returns its rows as plain objects. values go in `params` and replace
 * the `?`s, so user input is escaped by mysql2 and never pasted into the sql.
 *
 *   await query<{ name: string }>("SELECT name FROM artists WHERE name LIKE ?", ["%sza%"])
 *   // -> [{ name: "SZA" }]
 */
export async function query<Row>(sql: string, params: unknown[] = []): Promise<Row[]> {
  // tells next.js "this needs a real request". without it, next build would try to run the
  // query ahead of time (with no database around) and bake the result into a static page
  await connection();
  const [rows] = await pool.query<RowDataPacket[]>(sql, params);
  return rows as Row[];
}
