import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtemp, readFile} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

export async function GET() {
  const root = path.resolve(process.cwd(), '..');
  try {
    const dir = await mkdtemp(path.join(os.tmpdir(), 'genealogy-info-samples-'));
    const output = path.join(dir, 'samples.json');
    await promisify(execFile)(path.join(root, '.venv/bin/python'), [path.join(root, 'scripts/information_parser.py'),
      '--samples', path.join(root, 'tests/fixtures/information-samples.json'), '--output', output], {timeout:30000});
    return Response.json(JSON.parse(await readFile(output, 'utf8')));
  } catch (e) {
    return Response.json({error: e.message}, {status:500});
  }
}
