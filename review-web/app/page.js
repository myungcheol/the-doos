'use client';
import {useEffect, useState} from 'react';

const KINDS = {birth:'출생', death:'사망', burial_date:'이장·매장 날짜', burial_note:'묘소 원문',
  office:'관직', education:'학력·과거', general_information:'일반 부가 정보', unclassified:'미분류 원문', spouse_information:'배우자 정보', ambiguous_event:'사건 종류 불확실'};
const PRECISION = {year:'연', year_month:'연·월', year_month_day:'연·월·일', month:'월만', month_day:'월·일', day:'일만', year_day:'연·일'};

function dateSummary(date) {
  return `${date.year_text || '연도 미상'} / ${date.leap_month ? '윤' : ''}${date.month_text || '월 미상'} / ${date.day_text || '일 미상'} (서기 미환산)`;
}

function SpouseDetails({item, onSelect}) {
  if (item.kind !== 'spouse_information') return null;
  return <div><strong>{item.subject.relation_type === 'concubine' ? '첩' : '배우자'} {item.subject.label}</strong>
    <ul>{item.items.map((child,i) => <li key={i}>
      {onSelect ? <button onClick={() => onSelect(i)}>{KINDS[child.kind]}: {child.raw}</button> : <>{KINDS[child.kind]}: {child.raw}</>}
      {child.date && <div>{dateSummary(child.date)}</div>}
    </li>)}</ul>
  </div>;
}

export default function Home() {
  const [pages, setPages] = useState([]), [page, setPage] = useState('001');
  const [data, setData] = useState(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [person, setPerson] = useState(-1);
  const [info, setInfo] = useState(-1), [bands, setBands] = useState(true);
  const [cols, setCols] = useState(false), [variant, setVariant] = useState('original');
  const [itemIndex, setItemIndex] = useState(-1);
  const [childIndex, setChildIndex] = useState(-1);
  const [samples, setSamples] = useState(null), [samplesError, setSamplesError] = useState('');
  useEffect(() => { fetch('/api/pages').then(r => r.json()).then(setPages); }, []);

  async function run(selected = variant) {
    setLoading(true); setError(''); setData(null); setPerson(-1); setInfo(-1); setItemIndex(-1); setChildIndex(-1); setVariant(selected);
    try {
      const response = await fetch(`/api/analyze/${page}?variant=${selected}`);
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      setData(result);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }

  function rect(b, stroke, key, selected = false) {
    return <rect key={key} x={b[0]} y={b[1]} width={b[2]-b[0]} height={b[3]-b[1]}
      fill={selected ? 'rgba(255,255,0,0.25)' : 'none'} stroke={stroke} strokeWidth={selected ? 3 : 2} />;
  }

  const candidate = person >= 0 ? data?.people.candidates[person] : null;
  const activeItem = candidate?.information?.items[itemIndex];
  const selectedRefs = (activeItem?.items?.[childIndex] || activeItem)?.source_refs.map(r => r.region_index) || [];
  return <main style={{fontFamily:'sans-serif', padding:16}}>
    <h1>족보 인물 후보 검수</h1>
    <select value={page} onChange={e => {setPage(e.target.value); setData(null); setPerson(-1); setInfo(-1); setItemIndex(-1); setChildIndex(-1); setVariant('original');}}>
      {pages.map(p => <option key={p}>{p}</option>)}
    </select>{' '}
    <button onClick={() => run()} disabled={loading}>{loading ? '분석 중…' : 'OCR 및 후보 분석'}</button>{' '}
    <label><input type="checkbox" checked={bands} onChange={e => setBands(e.target.checked)}/>단</label>{' '}
    <label><input type="checkbox" checked={cols} onChange={e => setCols(e.target.checked)}/>열</label>
    <p>OCR은 CPU에서 시간이 걸립니다. 후보와 정보 귀속은 미검수 상태입니다.</p>
    <details onToggle={async e => {
      if (!e.currentTarget.open || samples) return;
      try {const response=await fetch('/api/information-samples');const value=await response.json();if(!response.ok)throw Error(value.error);setSamples(value.samples);}
      catch(e){setSamplesError(e.message);}
    }}><summary>T008 규칙 샘플 검수 — OCR 없이 확인</summary>
      <p>032쪽의 확인된 날짜 조각 1개와 가상 입력 예시입니다. 현재 스캔 페이지의 인물 정보가 아닙니다.</p>
      {samplesError && <p>{samplesError}</p>}
      {!samples && !samplesError && <p>샘플 불러오는 중…</p>}
      {samples?.map(sample => <article key={sample.id} style={{borderBottom:'1px solid #ccc',padding:8}}>
        <strong>{sample.kind === 'confirmed_fragment' ? '032쪽 확인 조각' : '가상 입력'}: {sample.source_text}</strong>
        <ul>{sample.items.map((item,i) => <li key={i}>{KINDS[item.kind]}: {item.raw}{item.date && <> — {dateSummary(item.date)} · {PRECISION[item.date.precision] || item.date.precision}</>}<SpouseDetails item={item}/></li>)}</ul>
      </article>)}
    </details>
    {data && <p>{data.rotation.applied ? <>
      기울기 {data.rotation.angle_degrees.toFixed(2)}° 감지, 보정본 저장됨.{' '}
      <button onClick={() => run('original')} disabled={loading || variant === 'original'}>원본 분석</button>{' '}
      <button onClick={() => run('corrected')} disabled={loading || variant === 'corrected'}>보정본 분석</button>{' '}
      현재: {variant === 'original' ? '원본' : '보정본'}
    </> : <>보정하지 않음: {data.rotation.reason}</>}</p>}
    {error && <pre>{error}</pre>}
    <div style={{display:'flex', gap:20, alignItems:'flex-start'}}>
      <div style={{position:'relative', width:'min(70vw, 800px)'}}>
        <img src={data && variant === 'corrected' && data.correctedUrl ? data.correctedUrl : `/api/image/${page}`}
          style={{display:'block', width:'100%'}} alt={`${page}쪽`}/>
        {data && <svg viewBox={`0 0 ${data.layout.width} ${data.layout.height}`}
          style={{position:'absolute', inset:0, width:'100%', height:'100%', pointerEvents:'none'}}>
          {bands && data.layout.bands.map((b,i) => rect(b.bbox,'red',`b${i}`))}
          {cols && data.layout.bands.flatMap((b,i) => b.columns.map((c,j) => rect(c.bbox,'blue',`c${i}-${j}`)))}
          {data.people.candidates.map((p,i) => rect(p.name_bbox,i === person ? 'lime' : 'orange',`p${i}`))}
          {candidate?.information_candidates.map((r,i) => rect(r.bbox, i === info || selectedRefs.includes(i) ? 'yellow' : '#00ffff', `info${i}`, i === info || selectedRefs.includes(i)))}
        </svg>}
      </div>
      <aside style={{maxWidth:420}}>{data && <>
        <h2>인물 후보 {data.people.candidates.length}명</h2>
        <p>주황: 이름 후보, 초록: 선택 인물, 청록: 정보 후보, 노랑: 선택 정보</p>
        {data.people.candidates.map((p,i) => <button key={i} onClick={() => {setPerson(i); setInfo(-1); setItemIndex(-1); setChildIndex(-1);}}>{p.name_text} (단 {p.band})</button>)}
        {candidate && <><h3>{candidate.name_text} 왼쪽 정보 후보</h3>
          {candidate.lineage_marker && <p>표지: {candidate.lineage_marker} — 아들 계통·후손 라인 (이름과 별도)</p>}
          {candidate.geometry_estimated && <p>옆 열과 합쳐진 OCR 상자를 분할한 후보입니다. 글자별 경계는 추정값이므로 원본과 확인해 주세요.</p>}
          <ul>{candidate.information_candidates.map((r,i) => <li key={i}>
            <button onClick={() => {setInfo(i); setItemIndex(-1); setChildIndex(-1);}} aria-pressed={i === info}
              style={{fontWeight:i === info ? 'bold' : 'normal'}}>{r.text} ({r.score.toFixed(2)})</button>
          </li>)}</ul>
          {candidate.information && <section>
            <h3>생몰·일반 정보 분류 후보</h3>
            <p>항목을 누르면 근거 OCR 상자가 노란색으로 표시됩니다. 배우자·첩의 생몰은 각각 해당 인물에게 속하며 모든 결과는 미검수 후보입니다.</p>
            {candidate.information.items.length === 0 && <p>분류할 본문이 없습니다.</p>}
            <ol>{candidate.information.items.map((item,i) => <li key={i} style={{marginBottom:12}}>
              <button onClick={() => {setItemIndex(i); setInfo(-1); setChildIndex(-1);}} aria-pressed={i === itemIndex}
                style={{fontWeight:i === itemIndex ? 'bold' : 'normal'}}>{KINDS[item.kind] || item.kind}: {item.raw}</button>
              {item.date && <div>{dateSummary(item.date)} · 원문 정밀도: {PRECISION[item.date.precision] || item.date.precision}</div>}
              <SpouseDetails item={item} onSelect={child => {setItemIndex(i); setChildIndex(child); setInfo(-1);}}/>
              {item.date && item.warnings?.length > 0 && <div>날짜 구성요소를 확인해 주세요.</div>}
            </li>)}</ol>
          </section>}
        </>}
      </>}</aside>
    </div>
  </main>;
}
