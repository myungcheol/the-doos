import {reviewDB} from '../../../../lib/review-db';

export async function GET(req, {params}) {
  const {page} = await params;
  const query = new URL(req.url).searchParams;
  const requested = query.get('import');
  if (!/^\d{3}$/.test(page) || (requested !== null && !/^\d{1,19}$/.test(requested))) {
    return Response.json({error:'쪽 또는 적재 번호가 올바르지 않습니다.'}, {status:400});
  }
  try {
    const db = reviewDB();
    const {rows:runs} = await db.query(`SELECT i.id, i.run_id, i.status,
      im.variant, im.width, im.height, im.sha256, im.rotation_degrees, r.finished_at
      FROM genealogy.pages p JOIN genealogy.page_imports i ON i.page_id=p.id
      JOIN genealogy.ocr_runs r ON r.id=i.run_id JOIN genealogy.page_images im ON im.id=r.image_id
      WHERE p.section='genealogy' AND p.page_key=$1 ORDER BY i.id DESC`, [page]);
    if (!runs.length) return Response.json({error:`${page}쪽은 아직 적재되지 않았습니다.`}, {status:404});
    const selected = requested ? runs.find(row => row.id === requested) : runs[0];
    if (!selected) return Response.json({error:'해당 쪽의 적재 기록이 없습니다.'}, {status:404});
    const {rows:[{extraction}]} = await db.query('SELECT extraction FROM genealogy.page_imports WHERE id=$1', [selected.id]);
    const {rows} = await db.query(`SELECT id,parent_region_id,kind,left_px,top_px,right_px,bottom_px
      FROM genealogy.ocr_regions WHERE run_id=$1 AND kind IN ('band','column')
      ORDER BY reading_order,id`, [selected.run_id]);
    const bbox = r => [r.left_px,r.top_px,r.right_px,r.bottom_px];
    const bands = rows.filter(r => r.kind === 'band').map(r => ({bbox:bbox(r),
      columns:rows.filter(c => c.parent_region_id === r.id).map(c => ({bbox:bbox(c)}))}));
    const {rows:records} = await db.query(`SELECT m.candidate_index, p.name_hanja, p.review_status,
      EXISTS(SELECT FROM genealogy.current_persons v WHERE v.id=p.id) AS visible,
      COALESCE((SELECT jsonb_agg(jsonb_build_object('id',f.id,'raw',f.raw_text,
        'kind',f.kind,'status',f.review_status,'explanation',COALESCE(f.explanation_manual,f.explanation_automatic))
        ORDER BY f.id) FROM genealogy.current_facts f WHERE f.occurrence_id=o.id), '[]') AS facts
      FROM genealogy.import_occurrences m JOIN genealogy.person_occurrences o ON o.id=m.occurrence_id
      JOIN genealogy.persons p ON p.id=o.person_id WHERE m.import_id=$1`, [selected.id]);
    const corrected = selected.variant === 'deskewed';
    return Response.json({people:extraction, layout:{width:selected.width,height:selected.height,bands},
      variant:corrected ? 'corrected' : 'original', correctedUrl:corrected ? `/api/corrected/${page}-${selected.sha256}` : null,
      selected:selected.id, runs, records, rotation:selected.rotation_degrees}, {headers:{'Cache-Control':'no-store'}});
  } catch (error) {
    console.error('Stored OCR lookup failed', error.code);
    return Response.json({error:'저장된 결과를 조회할 수 없습니다. DB 연결과 마이그레이션 008을 확인하세요.'},{status:503});
  }
}
