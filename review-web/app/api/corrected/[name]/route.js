import {readFile} from 'node:fs/promises';
import path from 'node:path';
export async function GET(_req,{params}) {const {name}=await params;if(!/^\d{3}-[a-f0-9]{64}$/.test(name))return new Response('Not found',{status:404});try{return new Response(await readFile(path.resolve(process.cwd(),`../data/ocr/deskew/${name}.png`)),{headers:{'Content-Type':'image/png'}})}catch{return new Response('Not found',{status:404})}}
