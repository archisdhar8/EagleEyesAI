"use client";

export type EvidenceKind = "VERIFIED_FACT" | "MODEL_OUTPUT" | "MARKET_IMPLIED" | "USER_BELIEF" | "AI_INTERPRETATION";
export type MissingEvidenceState = "UNAVAILABLE" | "INSUFFICIENT_DATA" | "STALE" | "PARTIAL_COVERAGE" | "UNSUPPORTED";

export type EvidenceTrustData = {
  kind: EvidenceKind;
  provider?: string | null;
  sourceUrl?: string | null;
  asOf?: string | null;
  effectiveDate?: string | null;
  methodology?: string | null;
  coverage?: string | number | null;
  freshness?: string | null;
  quality?: string | null;
  agreement?: string | null;
  marketQuality?: string | null;
  modelVersion?: string | null;
  assumptions?: string[];
  missingState?: MissingEvidenceState | null;
  knownAt?: string | null;
  currentAt?: string | null;
};

const KIND_LABELS: Record<EvidenceKind,string> = {
  VERIFIED_FACT:"Verified fact", MODEL_OUTPUT:"Model output", MARKET_IMPLIED:"Market-implied evidence",
  USER_BELIEF:"User belief", AI_INTERPRETATION:"AI interpretation",
};

function dateLabel(value?:string|null){if(!value)return"Unavailable";const dateOnly=/^\d{4}-\d{2}-\d{2}$/.test(value);return new Date(dateOnly?`${value}T12:00:00`:value).toLocaleString(undefined,{month:"short",day:"numeric",year:"numeric",hour:dateOnly?undefined:"numeric",minute:dateOnly?undefined:"2-digit"});}
function coverageLabel(value:EvidenceTrustData["coverage"]){if(value==null)return null;if(typeof value==="number")return `${Math.round(value<=1?value*100:value)}%`;return value.replaceAll("_"," ").toLowerCase();}

export function EvidenceKindBadge({kind}:{kind:EvidenceKind}){return <span className={`evidence-kind ${kind.toLowerCase()}`}>{KIND_LABELS[kind]}</span>;}

export function MissingEvidence({state,detail}:{state:MissingEvidenceState;detail?:string}){
  return <div className={`missing-evidence-state ${state.toLowerCase()}`} role="note"><strong>{state.replaceAll("_"," ")}</strong><span>{detail||"This evidence is not available and is not interpreted as neutral, unchanged, or zero."}</span></div>;
}

export function EvidenceTrust({data,label="Evidence details",compact=false}:{data:EvidenceTrustData;label?:string;compact?:boolean}){
  const dimensions=[
    data.coverage!=null?["Data coverage",coverageLabel(data.coverage)]:null,
    data.freshness?["Freshness",data.freshness.replaceAll("_"," ").toLowerCase()]:null,
    data.quality?["Evidence quality",data.quality.replaceAll("_"," ").toLowerCase()]:null,
    data.agreement?["Evidence agreement",data.agreement.replaceAll("_"," ").toLowerCase()]:null,
    data.marketQuality?["Market quality",data.marketQuality.replaceAll("_"," ").toLowerCase()]:null,
  ].filter(Boolean) as string[][];
  return <details className={`evidence-trust ${compact?"compact":""}`}>
    <summary><EvidenceKindBadge kind={data.kind}/><span>{label}</span>{data.missingState&&<b>{data.missingState.replaceAll("_"," ")}</b>}</summary>
    <div className="evidence-trust-body">
      {data.knownAt&&<div className="historical-truth"><span>As known on</span><strong>{dateLabel(data.knownAt)}</strong>{data.currentAt&&<><span>Current evidence</span><strong>{dateLabel(data.currentAt)}</strong></>}</div>}
      {data.missingState&&<MissingEvidence state={data.missingState}/>}
      {dimensions.length>0&&<div className="trust-dimensions">{dimensions.map(([key,value])=><span key={key}><b>{key}</b>{value}</span>)}</div>}
      <dl>
        {data.provider&&<div><dt>Provider / source</dt><dd>{data.sourceUrl?<a href={data.sourceUrl} target="_blank" rel="noreferrer">{data.provider} ↗</a>:data.provider}</dd></div>}
        {data.asOf&&<div><dt>Observed as of</dt><dd>{dateLabel(data.asOf)}</dd></div>}
        {data.effectiveDate&&<div><dt>Effective date</dt><dd>{dateLabel(data.effectiveDate)}</dd></div>}
        {data.methodology&&<div><dt>Methodology</dt><dd>{data.methodology}</dd></div>}
        {data.modelVersion&&<div><dt>Model version</dt><dd>{data.modelVersion}</dd></div>}
      </dl>
      {!!data.assumptions?.length&&<div className="trust-assumptions"><b>Assumptions</b>{data.assumptions.map(item=><span key={item}>{item}</span>)}</div>}
    </div>
  </details>;
}
