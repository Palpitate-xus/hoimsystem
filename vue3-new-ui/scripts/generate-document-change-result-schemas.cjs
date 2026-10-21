const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(value=>value!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai import document_change_contract as c
from app.ai import document_change_draft as d
from app.ai import document_change_view_contract as v
from app.ai.document_change_result import DocumentChangeGenerationResult,result_for_draft
from app.ai.document_extraction_view_contract import DocumentFrozenProvider,DocumentFrozenValidation
classes=[v.DocumentChangeRequest,v.DocumentChangeBinding,v.DocumentChangeContext,v.DocumentChangeSourcePacket,v.DocumentChangePrivateScopePacket,v.DocumentChangeResultPacket,v.DocumentChangeResultReference,v.DocumentChangeArtifactRecord,d.DocumentChangeDraft,d.ProviderReply,DocumentChangeGenerationResult,DocumentFrozenProvider,DocumentFrozenValidation]
def original(i):
 return c.DocumentChangeOriginal(schema_version='document_change_original_source_v1',original={'original_id':f'00000000-0000-0000-0000-{i:012}','content_hash':str(i)*64,'governance_hash':'a'*64},raw_bytes_hash=c.e.bytes_hash('x'),raw_bytes_length=1,codepoint_length=1,text='x')
s=c.DocumentChangeSource(schema_version=c.SCHEMA_VERSION,scope={'scope_id':'00000000-0000-0000-0000-000000000072','content_hash':'c'*64,'governance_hash':'d'*64},baseline=original(1),candidate=original(2),relationship_kind='comparison_only',same_guideline_family='unknown',rule_link_coverage='unknown',targets=[],rule_links=[],publications=[],member_count=2,inventory_hash='e'*64,hospital_wide_rule_inventory='not_provided',clinical_validation='not_provided')
r=result_for_draft(d.build_draft({'changes':[]},s,'3'*64),s,'3'*64).model_dump(mode='json');r.pop('document_change')
r['summary']=r['summary'].replace('0项','{count}项').replace('0条','{overlaps}条')
r['sections'][0]['source_ids']=['{scope_id}','{baseline_id}','{candidate_id}'];r['sections'][1]['source_ids']=['{scope_id}']
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':{m.__name__:m.model_json_schema() for m in classes},'fixed':{'system_prompt':d.SYSTEM_PROMPT,'task_prompt':d.TASK_PROMPT,'coverage':d.COVERAGE,'coverage_note':d.COVERAGE_NOTE,'overlap_note':d.OVERLAP_NOTE,'missing_data':list(v.MISSING_DATA),'explanation':r,'max_wire_bytes':c.MAX_CASE_BYTES,'max_changes':d.MAX_CHANGES,'max_spans_per_side':d.MAX_SPANS_PER_SIDE}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:4194304}));
for(const[name,value]of [['documentChangeResultSchemas.json',pack(data.models)],['documentChangeFixed.json',data.fixed]]){
 const file=path.join(root,'src/api/ai',name),content=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(file,'utf8')!==content)throw new Error(name+' differs from actual pure types');}else fs.writeFileSync(file,content);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}, ${Buffer.byteLength(content)} bytes\n`);
}
