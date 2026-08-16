"use client";

import { useState } from "react";
import { LEARNING_GLOSSARY } from "../../lib/learning";

export function ConceptGlossary({onOpen}:{onOpen:(module:string,lesson:string)=>void}){const [open,setOpen]=useState(false);return <><button className="theme-button learn-this-button" onClick={()=>setOpen(true)}>？ Learn this</button>{open&&<div className="concept-overlay" role="dialog" aria-modal="true" aria-label="Learning glossary"><button className="concept-backdrop" aria-label="Close learning glossary" onClick={()=>setOpen(false)}/><aside><header><div><span>Contextual learning</span><h2>Understand the term, then return to your work.</h2></div><button onClick={()=>setOpen(false)} aria-label="Close">×</button></header><div>{LEARNING_GLOSSARY.map(item=><article key={item.term}><h3>{item.term}</h3><p>{item.definition}</p><button onClick={()=>{setOpen(false);onOpen(item.module,item.lesson)}}>Open lesson →</button></article>)}</div></aside></div>}</>}
