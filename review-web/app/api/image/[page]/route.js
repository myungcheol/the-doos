import { readFile } from 'node:fs/promises';
import path from 'node:path';
export async function GET(_req,{params}) { const {page}=await params; if(!/^\d{3}$/.test(page)) return new Response('Not found',{status:404}); try {const bytes=await readFile(path.resolve(process.cwd(),`../scan/genealogy/${page}.jpg`));return new Response(bytes,{headers:{'Content-Type':'image/jpeg'}})} catch {return new Response('Not found',{status:404})} }
