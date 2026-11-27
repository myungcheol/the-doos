'use client';
import {useEffect, useRef, useState} from 'react';

const KINDS = {birth:'출생', death:'사망', burial_date:'이장·매장 날짜', burial_note:'묘소 원문',
  office:'관직', education:'학력·과거', general_information:'일반 부가 정보', unclassified:'미분류 원문', spouse_information:'배우자 정보', ambiguous_event:'사건 종류 불확실', date_unspecified:'날짜 (생몰 표지 미확인)'};
const PRECISION = {year:'연', year_month:'연·월', year_month_day:'연·월·일', month:'월만', month_day:'월·일', day:'일만', year_day:'연·일'};

const IMPORT_STATUS = {applied:'최초 적재', equivalent:'동일한 추출', needs_review:'기존 추출과 차이 있음'};

function dateSummary(date) {
  const year = date.year_number ? `${date.year_number}년 (${date.year_text})` : date.year_text || '연도 미상';
  const years = date.date_details?.candidate_years || [];
  const statuses = {
    resolved: `서기 ${date.gregorian_year}년`,
    ambiguous: `서기 후보 ${years.join(', ')}년`,
    conflict: '연도와 간지 불일치',
    unresolved: '연도 확인 필요',
  };
  const status = statuses[date.conversion_status] || (date.year_number ? '숫자 연도 판독' : '서기 미환산');
  return `${year} / ${date.leap_month ? '윤' : ''}${date.month_text || '월 미상'} / ${date.day_text || '일 미상'} (${status})${date.ocr_corrections?.length ? ' · 연도 OCR 보정 후보 포함' : ''}`;
}

const LIFE_KINDS = new Set(['birth', 'death', 'burial_date', 'date_unspecified']);

function InformationItems({items, emptyText, selectedIndex, onSelect}) {
  if (items.length === 0) return <p>{emptyText}</p>;
  return <ol>{items.map(({item, index}) => <li key={index} style={{marginBottom:12}}>
    <button onClick={() => onSelect(index)} aria-pressed={index === selectedIndex}
      style={{fontWeight:index === selectedIndex ? 'bold' : 'normal'}}>{KINDS[item.kind] || item.kind}: {item.raw}</button>
    {item.explanation?.automatic && <div>자동 풀이 후보: {item.explanation.automatic}</div>}
    {item.explanation?.manual && <div>수동 풀이: {item.explanation.manual}</div>}
    {!item.explanation?.automatic && !item.explanation?.manual && <div>한국어 풀이 없음 · 원문 확인 필요</div>}
    {item.date && <div>{dateSummary(item.date)} · 원문 정밀도: {PRECISION[item.date.precision] || item.date.precision}</div>}
    {item.ocr_marker_interpretation && <div>OCR 판독 보정 후보: {item.ocr_marker_interpretation.raw} → {item.ocr_marker_interpretation.interpreted_as} (뒤에 묘소 기록이 이어짐)</div>}
    {item.date && item.warnings?.some(warning => warning === 'date components out of range') && <div>날짜 구성요소를 확인해 주세요.</div>}
  </li>)}</ol>;
}

export default function Home() {
  const [pages, setPages] = useState([]), [page, setPage] = useState('001');
  const [data, setData] = useState(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [person, setPerson] = useState(-1);
  const [info, setInfo] = useState(-1), [bands, setBands] = useState(true);
  const [cols, setCols] = useState(false), [variant, setVariant] = useState('original');
  const [itemIndex, setItemIndex] = useState(-1);
  const [childIndex, setChildIndex] = useState(-1);
  const [tab, setTab] = useState('life');
  const viewportRef = useRef(null);
  const [viewport, setViewport] = useState({width:600, height:800});
  const [imageSize, setImageSize] = useState({width:688, height:948});
  const [zoom, setZoom] = useState(1);
  const [referencePages, setReferencePages] = useState({});
  useEffect(() => { fetch('/api/pages').then(r => r.json()).then(setPages); }, []);
  useEffect(() => {
    const observer = new ResizeObserver(entries => {
      const {width, height} = entries[0].contentRect;
      setViewport({width, height});
    });
    observer.observe(viewportRef.current);
    return () => observer.disconnect();
  }, []);

  const lookup = useRef(0);
  async function loadPage(targetPage, importId) {
    const request = ++lookup.current;
    setPage(targetPage);
    setLoading(true); setError(''); setData(null); setReferencePages({}); setPerson(-1); setInfo(-1); setItemIndex(-1); setChildIndex(-1); setVariant('original');
    try {
      const suffix = importId ? '?import=' + importId : '';
      const response = await fetch(`/api/analyze/${targetPage}${suffix}`);
      const result = await response.json();
      if (request !== lookup.current) return;
      if (!response.ok) throw Error(result.error);
      setVariant(result.variant);
      setData(result);
    } catch (e) { if (request === lookup.current) setError(e.message); } finally { if (request === lookup.current) setLoading(false); }
  }
  useEffect(() => { loadPage('001'); return () => { lookup.current++; }; }, []);
  useEffect(() => {
    const refs = data?.people.page_references || [];
    const targets = [...new Set(refs.filter(ref => ref.status === 'unprocessed').map(ref => ref.target_page))];
    if (targets.length === 0) return;
    let cancelled = false;
    Promise.all(targets.map(async target => {
      try {
        const response = await fetch(`/api/analyze/${String(target).padStart(3,'0')}`);
        const result = await response.json();
        return [target, response.ok ? result : {error:result.error || '대상 쪽 분석 실패'}];
      } catch (error) { return [target, {error:error.message}]; }
    })).then(entries => { if (!cancelled) setReferencePages(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [data]);

  function rect(b, stroke, key, selected = false) {
    return <rect key={key} x={b[0]} y={b[1]} width={b[2]-b[0]} height={b[3]-b[1]}
      fill={selected ? 'rgba(255,255,0,0.25)' : 'none'} stroke={stroke} strokeWidth={selected ? 3 : 2} />;
  }

  const record = data?.records.find(row => row.candidate_index === person);
  const candidate = person >= 0 ? data?.people.candidates[person] : null;
  const parentRelations = data?.people.parent_candidates?.relations || [];
  const parentEdge = parentRelations.find(edge => edge.child === person);
  const childEdges = parentRelations.filter(edge => edge.parent === person);
  const unresolvedParent = data?.people.parent_candidates?.unresolved.find(entry => entry.child === person);
  const crossPageReferences = (data?.people.page_references || []).filter(reference => reference.person === person);
  const bareName = value => value.replace(/^[子女女]/,'').replace(/□/g,'');
  function matchingTarget(reference) {
    const target = referencePages[reference.target_page];
    if (!target?.people) return [];
    return target.people.candidates.map((item,index) => ({item,index})).filter(({item}) => bareName(item.name_text) === bareName(candidate.name_text));
  }
  function openTarget(reference, targetIndex) {
    const target = referencePages[reference.target_page];
    if (!target?.people) return;
    setPage(String(reference.target_page).padStart(3,'0')); setVariant(target.variant); setData(target);
    setPerson(targetIndex); setInfo(-1); setItemIndex(-1); setChildIndex(-1); setTab('references');
  }
  const activeItem = candidate?.information?.items[itemIndex];
  const selectedRefs = (activeItem?.items?.[childIndex] || activeItem)?.source_refs.map(r => r.region_index) || [];
  const indexedInformation = candidate?.information?.items.map((item, index) => ({item, index})) || [];
  const lifeItems = indexedInformation.filter(({item}) => LIFE_KINDS.has(item.kind));
  const generalItems = indexedInformation.filter(({item}) => item.kind !== 'spouse_information' && !LIFE_KINDS.has(item.kind));
  const fitScale = Math.max(.01, Math.min(viewport.width/imageSize.width, viewport.height/imageSize.height));
  const scale = fitScale * zoom;
  return <main className="review-shell">
    <header className="review-toolbar">
    <h1>족보 인물 후보 검수</h1>
    <div className="toolbar-controls">
    <select aria-label="스캔 쪽" disabled={loading} value={page} onChange={e => loadPage(e.target.value)}>
      {pages.map(p => <option key={p}>{p}</option>)}
    </select>{' '}
    <button onClick={() => loadPage(page, data?.selected)} disabled={loading}>{loading ? '조회 중…' : '다시 조회'}</button>{' '}
    <label><input type="checkbox" checked={bands} onChange={e => setBands(e.target.checked)}/>단</label>{' '}
    <label><input type="checkbox" checked={cols} onChange={e => setCols(e.target.checked)}/>열</label>
    </div>
    </header>
    <div className="review-workspace">
      <section className="scan-panel" aria-label="스캔 이미지">
    <div className="image-controls">
      <div className="zoom-controls" aria-label="이미지 확대 및 축소">
        <button onClick={() => setZoom(value => Math.max(.5, value-.25))} disabled={zoom <= .5} aria-label="축소">−</button>
        <input aria-label="이미지 배율" type="range" min="50" max="400" step="25" value={zoom*100}
          onChange={event => setZoom(Number(event.target.value)/100)}/>
        <button onClick={() => setZoom(value => Math.min(4, value+.25))} disabled={zoom >= 4} aria-label="확대">＋</button>
        <button onClick={() => setZoom(1)}>화면 맞춤</button>
        <output>{Math.round(zoom*100)}%</output>
      </div>
    {data && <label>저장된 OCR 실행{' '}
      <select value={data.selected} onChange={e => loadPage(page, e.target.value)}>
        {data.runs.map(r => <option key={r.id} value={r.id}>
          #{r.run_id} · {r.variant === 'deskewed' ? `보정본 ${r.rotation_degrees.toFixed(2)}°` : '원본'} · {IMPORT_STATUS[r.status]}
        </option>)}
      </select>
    </label>}
    </div>
      <div className="scan-viewport" ref={viewportRef}>
      <div className="scan-canvas" style={{width:Math.max(viewport.width,imageSize.width*scale), height:Math.max(viewport.height,imageSize.height*scale)}}>
      <div className="scan-stage" style={{width:imageSize.width*scale, height:imageSize.height*scale}}>
        <img src={data && variant === 'corrected' && data.correctedUrl ? data.correctedUrl : `/api/image/${page}`}
          onLoad={e => setImageSize({width:e.currentTarget.naturalWidth, height:e.currentTarget.naturalHeight})}
          style={{display:'block', width:'100%', height:'100%'}} alt={`${page}쪽`}/>
        {data && <svg viewBox={`0 0 ${data.layout.width} ${data.layout.height}`}
          style={{position:'absolute', inset:0, width:'100%', height:'100%', pointerEvents:'none'}}>
          {bands && data.layout.bands.map((b,i) => rect(b.bbox,'red',`b${i}`))}
          {cols && data.layout.bands.flatMap((b,i) => b.columns.map((c,j) => rect(c.bbox,'blue',`c${i}-${j}`)))}
          {data.people.candidates.map((p,i) => rect(p.name_bbox,i === person ? 'lime' : 'orange',`p${i}`))}
          {tab === 'family' && parentEdge && rect(data.people.candidates[parentEdge.parent].name_bbox,'magenta','parent')}
          {tab === 'family' && childEdges.map(edge => rect(data.people.candidates[edge.child].name_bbox,'magenta',`child${edge.child}`))}
          {candidate?.information_candidates.map((r,i) => rect(r.bbox, i === info || selectedRefs.includes(i) ? 'yellow' : '#00ffff', `info${i}`, i === info || selectedRefs.includes(i)))}
        </svg>}
      </div>
      </div>
      </div>
      <p className="scan-caption">{page}쪽 · {variant === 'corrected' ? '보정본' : '원본'} · 정보 항목을 누르면 근거 영역이 노란색으로 표시됩니다.</p>
      </section>
      <aside className="review-panel" aria-label="인물 정보 검수">
        {error && <pre role="alert" className="review-error">{error}</pre>}
        {!data && !error && <p className="empty-state">{loading ? '저장된 OCR 결과를 불러오는 중입니다.' : '쪽을 선택하세요.'}</p>}
        {data && <>
        <div className="person-picker">
        <h2>인물 후보 {data.people.candidates.length}명</h2>
        <select aria-label="검수할 인물" value={person} onChange={e => {setPerson(Number(e.target.value));setInfo(-1);setItemIndex(-1);setChildIndex(-1);setTab('life');}}>
          <option value={-1}>인물을 선택하세요</option>
          {data.people.candidates.map((p,i) => <option key={i} value={i}>{p.name_text} (단 {p.band})</option>)}
        </select>
        <p>주황: 이름 · 초록: 선택 인물 · 청록: 정보 · 노랑: 선택 정보</p>
        {candidate && <nav className="detail-tabs" aria-label="검수 정보 종류">
          {[['current','현재 검수값'],['raw','원문'],['life','생몰'],['spouses','배우자·혼인'],['general','일반정보'],['family','부모·자녀'],['references','다른 쪽 참조']].map(([key,label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}
        </nav>}
        </div>
        {candidate && <div className="person-details"><h3>{candidate.name_text}</h3>
          {tab === 'current' && <section>
            {record ? <>
              <p>{record.name_hanja || '이름 미상'} · {{pending:'미검수',confirmed:'확정',rejected:'거절'}[record.review_status]}
                {record.visible ? '' : ' · 서비스 조회 제외'}</p>
              <h4>현재 조회되는 부가 정보</h4>
              {record.facts.length ? <ul>{record.facts.map(f => <li key={f.id}>
                {KINDS[f.kind]} · {f.raw}{f.explanation && <div>{f.explanation}</div>}
              </li>)}</ul> : <p>표시할 부가 정보가 없습니다.</p>}
            </> : <p>기존 인물과 대조가 필요한 추출입니다.</p>}
          </section>}
          {candidate.missing_name_characters > 0 && <p>OCR 이름 상자는 더 긴데 글자를 {candidate.missing_name_characters}자 덜 읽었습니다. □는 판독이 필요한 누락 글자입니다.</p>}
          {candidate.lineage_marker && <p>표지: {candidate.lineage_marker} — 아들 계통·후손 라인 (이름과 별도)</p>}
          {candidate.geometry_estimated && <p>옆 열과 합쳐진 OCR 상자를 분할한 후보입니다. 글자별 경계는 추정값이므로 원본과 확인해 주세요.</p>}
          <section hidden={tab !== 'family'}>
            <h3>같은 쪽 부모·자녀 후보</h3>
            <p>자홍색 상자는 관계 후보입니다. 윗단 이름의 OCR 누락이나 잘못된 이름, 페이지 경계 때문에 관계가 틀릴 수 있습니다. 배우자는 자녀의 부모로 자동 추가하지 않습니다.</p>
            <h4>부모 후보</h4>
            {parentEdge ? <p><button onClick={() => {setPerson(parentEdge.parent);setInfo(-1);setItemIndex(-1);setChildIndex(-1);}}>{data.people.candidates[parentEdge.parent].name_text} (단 {data.people.candidates[parentEdge.parent].band})</button> · {parentEdge.method === 'same_column' ? '바로 윗단 같은 열' : '윗단 오른쪽 첫 인물'} · 미검수</p> : <p>{unresolvedParent?.reason === 'upper_band_outside_page' ? '윗단이 이 쪽에 없어 보류' : '윗단 오른쪽에 부모 후보가 없어 보류'} — 다른 쪽 연결은 아직 분석하지 않습니다.</p>}
            <h4>자녀 후보</h4>
            {childEdges.length ? <ul>{childEdges.map(edge => <li key={edge.child}><button onClick={() => {setPerson(edge.child);setInfo(-1);setItemIndex(-1);setChildIndex(-1);}}>{data.people.candidates[edge.child].name_text} (단 {data.people.candidates[edge.child].band})</button> · {edge.method === 'same_column' ? '바로 윗단 같은 열' : '윗단 오른쪽 첫 인물'} · 미검수{edge.warnings.includes('female_marker_requires_review') ? ' · 女 항목 확인 필요' : ''}</li>)}</ul> : <p>같은 쪽에서 찾은 자녀 후보가 없습니다. 자녀가 없다는 뜻은 아닙니다.</p>}
          </section>
          <section hidden={tab !== 'references'}>
            <h3>다른 쪽 인물 참조 후보</h3>
            <p>명시된 上·下 쪽 표지와 대상 쪽 이름만 대조합니다. 같은 이름만으로 전역 인물을 합치지 않으며, 모든 결과는 미검수입니다.</p>
            {crossPageReferences.length === 0 && <p>이 인물 가까이에서 찾은 다른 쪽 참조 표지가 없습니다.</p>}
            <ul>{crossPageReferences.map((reference, index) => {
              const target = referencePages[reference.target_page];
              const matches = matchingTarget(reference);
              return <li key={index}>
                <strong>{reference.raw}</strong> → {String(reference.target_page).padStart(3,'0')}쪽 · {reference.direction === 'up' ? '위쪽 참조' : '아래쪽 참조'}{reference.ocr_direction_uncertain ? ' · OCR 방향 판독 확인 필요' : ''}
                {reference.status === 'scan_missing' ? <div>대상 스캔 누락: 연결 보류</div> : !target ? <div>대상 쪽 조회 중…</div> : target.error ? <div>대상 쪽 조회: {target.error}</div> : matches.length === 1 ? <div><button onClick={() => openTarget(reference,matches[0].index)}>{matches[0].item.name_text} (단 {matches[0].item.band})</button> · 이름 일치 출현 후보 · 미검수</div> : matches.length > 1 ? <div>대상 쪽에 같은 이름이 {matches.length}개여서 연결 보류</div> : <div>대상 쪽에서 같은 이름을 찾지 못함 — OCR 차이 또는 원본 확인 필요</div>}
              </li>;
            })}</ul>
          </section>
          <section hidden={tab !== 'raw'}><h4>왼쪽 정보 원문 후보</h4>
          <ul>{candidate.information_candidates.map((r,i) => <li key={i}>
            <button onClick={() => {setInfo(i); setItemIndex(-1); setChildIndex(-1);}} aria-pressed={i === info}
              style={{fontWeight:i === info ? 'bold' : 'normal'}}>{r.text} ({r.score.toFixed(2)})</button>
          </li>)}</ul></section>
          {candidate.information && <section hidden={tab !== 'life'}>
            <h3>본인 생몰 정보</h3>
            <p>본인의 출생·사망·매장 날짜와 생몰 표지를 확인하지 못한 날짜 후보를 표시합니다. 배우자·첩의 생몰은 배우자·혼인 탭에서 확인합니다.</p>
            <InformationItems items={lifeItems} emptyText="본인 생몰 정보 후보가 없습니다." selectedIndex={itemIndex}
              onSelect={i => {setItemIndex(i); setInfo(-1); setChildIndex(-1);}}/>
          </section>}
          {candidate.spouses && <section hidden={tab !== 'spouses'}>
            <h3>T009 배우자·혼인 후보 — 초안</h3>
            <p>각 항목은 별도 인물 후보입니다. 본부인 여부는 추정하지 않으며, 친족 정보로 보이는 부분은 보류합니다.</p>
            <ul>{candidate.spouses.people.map(p => {
              const relation = candidate.spouses.marriages.find(m => m.to === p.id);
              const spouseItemIndex = candidate.information.items.findIndex(i => i.subject?.id === p.id);
              const spouseItem = candidate.information.items[spouseItemIndex];
              return <li key={p.id} style={{marginBottom:12}}>
                <button onClick={() => {setItemIndex(spouseItemIndex);setChildIndex(-1);setInfo(-1);}} aria-pressed={spouseItemIndex === itemIndex}>
                  {relation?.relation_type === 'concubine' ? '첩' : '배우자'} {p.designation_raw}
                </button>
                <div>{candidate.name_text} ↔ {p.designation_raw} · 미검수 혼인 후보</div>
                {spouseItem && <div>배우자 범위 원문: {spouseItem.raw}</div>}
                {spouseItem?.explanation?.automatic && <div>자동 풀이 후보: {spouseItem.explanation.automatic}</div>}
                <ul>{p.information_items.filter(i => i.date).map((i,j) => <li key={j}>{KINDS[i.kind]}: {dateSummary(i.date)}{i.explanation?.automatic && <div>자동 풀이 후보: {i.explanation.automatic}</div>}</li>)}</ul>
                {p.unresolved_items.length > 0 && <div>친족 소속 가능성이 있는 정보 {p.unresolved_items.length}건 보류</div>}
              </li>;
            })}</ul>
            {candidate.spouses.unresolved_scopes.length > 0 && <p>친족 구간의 배우자 언급 {candidate.spouses.unresolved_scopes.length}건은 혼인 관계로 만들지 않았습니다.</p>}
          </section>}
          {candidate.information && <section hidden={tab !== 'general'}>
            <h3>일반정보</h3>
            <p>관직·학력·묘소 설명과 아직 분류하지 못한 본인 정보를 표시합니다. 배우자 범위는 이 탭에서 제외합니다.</p>
            <InformationItems items={generalItems} emptyText="일반정보 후보가 없습니다." selectedIndex={itemIndex}
              onSelect={i => {setItemIndex(i); setInfo(-1); setChildIndex(-1);}}/>
          </section>}
        </div>}
      </>}</aside>
    </div>
  </main>;
}
