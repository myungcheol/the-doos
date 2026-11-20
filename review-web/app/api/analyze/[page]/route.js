import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, stat, mkdir, copyFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
const exec=promisify(execFile); const cache=new Map();
export async function GET(req,{params}) {
 const {page}=await params; if(!/^\d{3}$/.test(page)) return new Response('Not found',{status:404});
 const variant=new URL(req.url).searchParams.get('variant')==='corrected'?'corrected':'original'; const key='vertical-retry-positional-year-v1:'+page+':'+variant;
 if(cache.has(key)) return Response.json(cache.get(key));
 const root=path.resolve(process.cwd(),'..'), img=path.join(root,'scan/genealogy',`${page}.jpg`), python=path.join(root,'.venv/bin/python');
 try {await stat(img); const dir=await mkdtemp(path.join(os.tmpdir(),'genealogy-review-')); const layout=path.join(dir,'layout.json'), ocr=path.join(dir,'ocr.json'), result=path.join(dir,'people.json'), preview=path.join(dir,'corrected.png');
 await exec(python,[path.join(root,'scripts/preprocess_page.py'),img,'--output',layout,'--deskew-output',preview],{cwd:root,timeout:120000});
 const processed=JSON.parse(await readFile(layout,'utf8')); let correctedUrl=null, selected=img;
 if(processed.rotation.applied){const bytes=await readFile(preview),hash=createHash('sha256').update(bytes).digest('hex'), outdir=path.join(root,'data/ocr/deskew'); await mkdir(outdir,{recursive:true}); const target=path.join(outdir,`${page}-${hash}.png`); try {await copyFile(preview,target,constants.COPYFILE_EXCL)} catch(e){if(e.code!=='EEXIST')throw e} correctedUrl=`/api/corrected/${page}-${hash}`; if(variant==='corrected')selected=target;}
 if(variant==='original' && processed.rotation.applied){const originalLayout=path.join(dir,'original.json'); await exec(python,[path.join(root,'scripts/preprocess_page.py'),img,'--output',originalLayout],{cwd:root,timeout:120000}); await copyFile(originalLayout,layout);}
 await exec(python,[path.join(root,'scripts/ocr_image.py'),selected,'--layout',layout,'--output',ocr],{cwd:root,timeout:300000,maxBuffer:1024*1024});
 await exec(python,[path.join(root,'scripts/person_candidates.py'),ocr,layout,'--output',result],{cwd:root,timeout:30000});
 const data={layout:JSON.parse(await readFile(layout,'utf8')),rotation:processed.rotation,correctedUrl,variant,people:JSON.parse(await readFile(result,'utf8'))}; cache.set(key,data); return Response.json(data);
 } catch(e) {return Response.json({error:String(e.stderr||e.message)},{status:500})}
}
