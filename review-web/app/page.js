'use client';
import {useEffect, useState} from 'react';

export default function Home() {
  const [pages, setPages] = useState([]), [page, setPage] = useState('001');
  const [data, setData] = useState(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [person, setPerson] = useState(-1);
  const [info, setInfo] = useState(-1), [bands, setBands] = useState(true);
  const [cols, setCols] = useState(false), [variant, setVariant] = useState('original');
  useEffect(() => { fetch('/api/pages').then(r => r.json()).then(setPages); }, []);

  async function run(selected = variant) {
    setLoading(true); setError(''); setData(null); setPerson(-1); setInfo(-1); setVariant(selected);
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
  return <main style={{fontFamily:'sans-serif', padding:16}}>
    <h1>족보 인물 후보 검수</h1>
    <select value={page} onChange={e => {setPage(e.target.value); setData(null); setPerson(-1); setInfo(-1); setVariant('original');}}>
      {pages.map(p => <option key={p}>{p}</option>)}
    </select>{' '}
    <button onClick={() => run()} disabled={loading}>{loading ? '분석 중…' : 'OCR 및 후보 분석'}</button>{' '}
    <label><input type="checkbox" checked={bands} onChange={e => setBands(e.target.checked)}/>단</label>{' '}
    <label><input type="checkbox" checked={cols} onChange={e => setCols(e.target.checked)}/>열</label>
    <p>OCR은 CPU에서 시간이 걸립니다. 후보와 정보 귀속은 미검수 상태입니다.</p>
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
          {candidate?.information_candidates.map((r,i) => rect(r.bbox, i === info ? 'yellow' : '#00ffff', `info${i}`, i === info))}
        </svg>}
      </div>
      <aside style={{maxWidth:420}}>{data && <>
        <h2>인물 후보 {data.people.candidates.length}명</h2>
        <p>주황: 이름 후보, 초록: 선택 인물, 청록: 정보 후보, 노랑: 선택 정보</p>
        {data.people.candidates.map((p,i) => <button key={i} onClick={() => {setPerson(i); setInfo(-1);}}>{p.name_text} (단 {p.band})</button>)}
        {candidate && <><h3>{candidate.name_text} 왼쪽 정보 후보</h3>
          {candidate.lineage_marker && <p>표지: {candidate.lineage_marker} — 아들 계통·후손 라인 (이름과 별도)</p>}
          {candidate.geometry_estimated && <p>옆 열과 합쳐진 OCR 상자를 분할한 후보입니다. 글자별 경계는 추정값이므로 원본과 확인해 주세요.</p>}
          <ul>{candidate.information_candidates.map((r,i) => <li key={i}>
            <button onClick={() => setInfo(i)} aria-pressed={i === info}
              style={{fontWeight:i === info ? 'bold' : 'normal'}}>{r.text} ({r.score.toFixed(2)})</button>
          </li>)}</ul>
        </>}
      </>}</aside>
    </div>
  </main>;
}
