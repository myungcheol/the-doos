import { readdir } from 'node:fs/promises';
import path from 'node:path';
export async function GET() { const dir=path.resolve(process.cwd(),'../scan/genealogy'); const pages=(await readdir(dir)).filter(n=>/^\d{3}\.jpg$/.test(n)).sort().map(n=>n.slice(0,3)); return Response.json(pages); }
