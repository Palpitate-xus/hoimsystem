import {supportCanonical as canonical,supportDigest as digest,supportHash as hash} from '../inpatientSupport';
import {documentUtf8,documentBytesHash} from './documentEvidence';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {scalarJsonValue} from './researchCohortOriginalJson';
import {researchCohortSchemaMatches} from './researchCohortSources';
import packed from './researchCohortResultSchemas.json';
import policy from './researchCohortResultPolicy.json';
const models=decodeGeneratedSchemas(packed),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort());
const cp=v=>Array.from(v),meaningful=v=>typeof v==='string'&&Array.from(v.replace(/\ufeff/gu,'')).some(c=>!/\s/u.test(c)&&!/[\u001c-\u001f\u0085]/u.test(c));
export const researchCohortResultPolicy=Object.freeze(structuredClone(policy));
export function researchWholePart(value){try{return scalarJsonValue(value)&&documentUtf8(canonical(value)).length<=policy.max_bytes;}catch{return false;}}
export async function researchCitationCatalog(source,{current=()=>true}={}){
 if(!current()||!researchWholePart(source)||!researchCohortSchemaMatches('ResearchCohortSource',source))throw new Error('完整研究公开来源闭集无效');
 const projection=await digest(source),targets=[];let bytes=0;
 const add=async(path,text,category)=>{if(typeof text!=='string'||text.length===0)return;if(!current())throw new Error('研究核对主体已变化');const value={target_token:await digest([source.source_id,projection,path]),category,source_path:path,text_hash:await documentBytesHash(text),text};bytes+=documentUtf8(canonical(value)).length;if(targets.length>=policy.max_targets||bytes>policy.max_bytes)throw new Error('完整研究引文目录超出容量');targets.push(value);};
 const criteria=async(node,path)=>{if(typeof node==='string')await add(path,node,'criteria_declaration');else if(Array.isArray(node)){for(let i=0;i<node.length;i++)await criteria(node[i],`${path}/${i}`);}else if(object(node)){for(const key of Object.keys(node).sort())await criteria(node[key],`${path}/${key}`);}};
 await criteria(source.criteria,'/criteria');
 for(let i=0;i<source.outcomes.length;i++)for(let j=0;j<source.outcomes[i].leaves.length;j++){
  const leaf=source.outcomes[i].leaves[j],path=`/outcomes/${i}/leaves/${j}`;await add(`${path}/reason`,leaf.reason,'record_scope_reason');
  for(let k=0;k<leaf.evidence.length;k++){await add(`${path}/evidence/${k}/quote`,leaf.evidence[k].quote,'recorded_evidence_quote');await add(`${path}/evidence/${k}/reason`,leaf.evidence[k].reason,'record_scope_reason');}
 }
 for(let i=0;i<source.limitations.length;i++)await add(`/limitations/${i}`,source.limitations[i],'source_limitation');
 if(!current())throw new Error('研究核对主体已变化');return {schema_version:'research_public_citation_catalog_v1',source_projection_hash:projection,targets};
}
export async function verifyResearchDraft(value,source,{current=()=>true}={}){try{
 if(!current()||!researchWholePart(value)||!generatedSchemaMatches(models,'ResearchCohortDraft',value)||value.research_source_id!==source.source_id||value.source_projection_hash!==await digest(source)||!hash(value.source_projection_hash))return false;
 const catalog=await researchCitationCatalog(source,{current}),targets=new Map(catalog.targets.map(v=>[v.target_token,v]));
 for(const q of value.questions){if(![q.title,q.observation,q.clarification_question].every(meaningful))return false;const seen=new Set(),kinds=new Set();for(const c of q.citations){
  const key=canonical([c.target_token,c.text_hash,c.start,c.end,c.quote]),target=targets.get(c.target_token);if(seen.has(key)||!target||c.end<=c.start||c.end>cp(target.text).length||cp(target.text).slice(c.start,c.end).join('')!==c.quote||c.text_hash!==target.text_hash)return false;seen.add(key);kinds.add(target.category);
 }if(q.category==='recorded_evidence_question'&&!kinds.has('recorded_evidence_quote')||q.category==='standard_question'&&!kinds.has('criteria_declaration'))return false;}
 return current();
}catch{return false;}}
export async function verifyResearchResult(value,source,{current=()=>true}={}){try{
 if(!researchWholePart(value)||!await verifyResearchDraft(value.question_draft,source,{current}))return false;
 const rebuilt={schema_version:'research_cohort_result_v1',research_source_id:source.source_id,source_projection_hash:await digest(source),summary:policy.summary,deterministic_evaluation:{rule_id:source.recipe.rule_id,criteria_hash:await digest(source.criteria),counts:source.counts,outcomes:source.outcomes.map(({patient_token,truth,interpretation})=>({patient_token,truth,interpretation}))},question_draft:value.question_draft,limitations:[...source.limitations,...policy.limitations],requires_human_review:true,no_business_write:true,no_automatic_export:true};
 return current()&&same(value,rebuilt);
}catch{return false;}}
export async function resolveResearchCitation(citation,source,{current=()=>true}={}){try{
 if(!keys(citation,['target_token','text_hash','start','end','quote'])||!Number.isSafeInteger(citation.start)||!Number.isSafeInteger(citation.end)||citation.start<0||citation.end<=citation.start)return null;
 const catalog=await researchCitationCatalog(source,{current}),target=catalog.targets.find(t=>t.target_token===citation.target_token);if(!current()||!target||target.text_hash!==citation.text_hash||citation.end>cp(target.text).length||cp(target.text).slice(citation.start,citation.end).join('')!==citation.quote)return null;return target;
}catch{return null;}}
