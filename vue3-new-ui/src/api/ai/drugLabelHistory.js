import {parseDrugLabelFrozenJson} from './drugLabelResults';

const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const own=(value,key)=>object(value)&&Object.hasOwn(value,key);
const evidenceMarker=row=>row?.kind==='drug_label_source'||typeof row?.source_id==='string'&&row.source_id.startsWith('drug_label_source:');
function contextMarkers(value){return object(value)&&(value.source_domain==='released_drug_label_original'||['drug_label_binding','drug_label_source','drug_label_source_binding_id'].some(key=>own(value,key))||own(value.selected_sources,'drug_label_source_binding_id'));}
function payloadMarkers(value){return object(value)&&(contextMarkers(value.context)||own(value.input,'drug_label_source_binding_id'));}
export function drugLabelRunHasNativeMarkers(value){
 if(!object(value))return false;
 if(value.feature_key==='drug_label_extraction'||['drug_label_source_binding_id','drug_label_findings','drug_label_artifact'].some(key=>own(value,key))||own(value.result,'drug_label_extraction')||value.result?.schema_version==='drug_label_result_pointer_v1'||payloadMarkers(value.frozen_request?.payload)||contextMarkers(value.context))return true;
 for(const key of ['input_json','evidence_json','context_metadata_json']){
  const raw=value.raw_frozen_json?.[key];if(typeof raw!=='string')continue;
  try{const parsed=parseDrugLabelFrozenJson(raw);if(payloadMarkers(parsed?.payload)||contextMarkers(parsed)||Array.isArray(parsed)&&parsed.some(evidenceMarker))return true;}catch{if(/"(?:drug_label_source_binding_id|drug_label_binding|drug_label_source)"\s*:/u.test(raw))return true;}
 }
 return Array.isArray(value.evidence)&&value.evidence.some(evidenceMarker);
}
