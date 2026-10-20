import { supportCanonical, supportDigest, supportId, supportKinds, verifySupportSource } from "@/api/inpatientSupport";
const pick=(value,fields)=>Object.fromEntries(fields.filter(key=>Object.hasOwn(value,key)).map(key=>[key,JSON.parse(JSON.stringify(value[key]))]));
const header=source=>pick(source,["source_id","content_hash","governance_hash","support_source_id","kind","schema_version","event_at","recorded_at"]);
const laboratory=source=>({...pick(source,["source_id","content_hash","lab_source_id","collected_at_utc","registered_at","available_at"]),analyte_key:source.snapshot.mapping.analyte_key,original:pick(source.snapshot.original.observation,["value_kind","value_num","unit"]),qualitative_text_provided:false});
const point=(source,key)=>({...pick(source,["source_id","content_hash","observation_id","observed_at","recorded_at"]),measurement:JSON.parse(JSON.stringify(source.payload.measurements[key]))});
const respiratory=source=>({...header(source),facts:pick(source.payload,["start_at","verified_until_at","ended_at","delivery_mode","continuity_confirmed"])});
export const supportMissingData = Object.freeze(["仅所选一条原资料及其明确关联，不代表完整交班、24小时最差状态或完整SOFA","原件记录与医生当前核实不代替独立临床验证；不提供脓毒症确诊、排除、概率或自动治疗"]);
export const supportReferencesValid=refs=>!!refs&&supportId(refs.support_source_id)&&Object.hasOwn(supportKinds,refs.support_source_kind);
export async function projectSupportSource(source){
  const kind=source.kind,p=source.payload,r=source.reference_snapshots,result={...header(source),source_verification:"explicit_human_record_not_independently_verified",clinical_review_signed:source.author_qualification.clinical_review_signed===true,historical_prediction:false,quantity_conversion_performed:false,sofa_provided:false,diagnosis_provided:false,probability_provided:false,complete_handover_provided:false};
  if(kind==="map")result.facts=pick(p,["observed_at","map","measurement_method"]);
  else if(kind==="respiratory_support")result.facts=respiratory(source).facts;
  else if(kind==="arterial_pair"){result.facts=pick(p,["arterial_sample_confirmed","same_sampling_state_confirmed","fio2_applicability_confirmed"]);result.reference_facts={pao2:laboratory(r.pao2),fio2:point(r.fio2,"fio2"),support:respiratory(r.support)};}
  else if(kind==="vasoactive"){result.facts={...pick(p,["start_at","verified_until_at","ended_at","continuity_confirmed"]),dose_input:pick(p.dose_input,["mode","rate","concentration","pump_rate","weight_applicability_confirmed"])};result.reference_facts={drug_mapping:pick(r.drug_mapping,["mapping_id","source_id","content_hash","governance_hash","drug_key","active_moiety_basis"]),weight:r.weight?point(r.weight,"body_weight"):null,origin:r.origin?pick(r.origin,["source_id","content_hash","administration_id","time_basis"]):null};result.stream_identity_hash=await supportDigest(p.stream_identity);}
  else if(kind==="infection_episode"){result.facts=pick(p,["infection_status","clinical_scope_start_at","clinical_scope_end_at","first_suspected_at","onset_at","onset_time_basis"]);result.reference_facts={evidence:r.evidence.map(item=>item.schema_version==="diagnosis_review_evidence_v1"?{...pick(item,["source_id","content_hash","review_id","time_basis"]),certainty:item.facts.review.certainty,diagnosis_text_provided:false}:laboratory(item))};}
  else throw new Error("原资料类型未实现公开投影");
  return result;
}
export async function verifySupportContext(packet,patientId,admissionId,references=null){
  try{const source=packet?.support_source,original=packet?.support_source_provenance;if(!source||!original||original.status!=="active"||original.eligible!==true||Object.hasOwn(packet,"scope")&&packet.scope!=="inpatient_support_original"||Object.hasOwn(packet,"missing_data")&&supportCanonical(packet.missing_data)!==supportCanonical(supportMissingData)||Object.hasOwn(packet,"selected_sources")&&supportCanonical(packet.selected_sources)!==supportCanonical({support_source_id:source.support_source_id,support_source_kind:source.kind})||!await verifySupportSource(original,source.kind,patientId,admissionId,true)||references&&(!supportReferencesValid(references)||source.support_source_id!==references.support_source_id||source.kind!==references.support_source_kind))return false;const projected=await projectSupportSource(original);return supportCanonical(projected)===supportCanonical(source)&&await supportDigest(projected)===packet.support_public_hash;}catch{return false;}
}
const invalid=item=>({...item,title:"原支持资料依据未能核对",content:"原资料索引与当前冻结来源不一致，无法展开。"});
export async function resolveSupportEvidence(item,packet,patientId,admissionId,references=null){
  if(!item)return null;let index;try{index=JSON.parse(item.content);}catch{if(item.kind==="knowledge")return item;return invalid(item);}
  if(item.kind==="knowledge"&&(!index||typeof index!=="object"||!Object.hasOwn(index,"context_path")))return item;
  if(!index||Object.keys(index).join(",")!=="context_path"||index.context_path!=="context.support_source"||item.source_id!==packet?.support_source?.source_id||!await verifySupportContext(packet,patientId,admissionId,references))return invalid(item);
  return {...item,title:"本地冻结原件核对（完整正文不发送模型）",content:JSON.stringify({support_source:packet.support_source,support_source_provenance:packet.support_source_provenance},null,2)};
}
