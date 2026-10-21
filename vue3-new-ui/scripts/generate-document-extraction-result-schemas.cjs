const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {pack}=require('./surgery-schema-storage.cjs');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(value=>value!=='--check'))throw new Error('Only --check accepted');
const code=String.raw`
import json,sys
from app.ai import document_extraction_contract as c
from app.ai import document_extraction_view_contract as v
from app.ai.document_extraction_result import DocumentExtractionGenerationResult,result_for_draft
classes=[c.DocumentExtractionRequest,c.DocumentExtractionSource,c.DocumentSpanDraft,c.DocumentExtractionReply,c.DocumentExtractionDraft,v.DocumentExtractionBinding,v.DocumentExtractionContext,v.DocumentFrozenProvider,v.DocumentFrozenValidation,v.DocumentExtractionAnchorRecord,DocumentExtractionGenerationResult]
s=c.DocumentExtractionSource(schema_version='document_extraction_source_v1',original={'original_id':'00000000-0000-0000-0000-000000000001','content_hash':'1'*64,'governance_hash':'2'*64},raw_bytes_hash=c.bytes_hash('x'),raw_bytes_length=1,codepoint_length=1,text='x')
d=c.parse_extraction_reply({'spans':[{'proposed_heading':'x','clause_kind':'other','start':0,'end':1,'quote':'x'}]},s,'3'*64)
r=result_for_draft(d,s,'3'*64).model_dump(mode='json');r.pop('document_extraction')
assert r['summary'].count('1')==1
r['summary']=r['summary'].replace('1','{count}')
for section in r['sections']:section['source_ids']=['{source_id}']
assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps({'models':{m.__name__:m.model_json_schema() for m in classes},'fixed':{'system_prompt':c.EXTRACTION_SYSTEM_PROMPT,'task_prompt':c.EXTRACTION_TASK_PROMPT,'coverage_note':c.INCOMPLETE_COVERAGE_NOTE,'explanation':r,'max_task_utf8_bytes':c.MAX_EXTRACTION_TEXT_BYTES,'max_spans':c.MAX_EXTRACTION_SPANS}},ensure_ascii=False,sort_keys=True,separators=(',',':')))
`;
const data=JSON.parse(execFileSync(process.env.HOIM_TEST_PYTHON||'/home/xusheng/miniconda3/bin/python',['-c',code],{cwd:path.join(root,'../fastapi_be'),encoding:'utf8',maxBuffer:2097152}));
for(const [name,value]of [['documentExtractionSchemas.json',pack(data.models)],['documentExtractionFixed.json',data.fixed]]){
 const file=path.join(root,'src/api/ai',name),content=JSON.stringify(value)+'\n';
 if(check){if(fs.readFileSync(file,'utf8')!==content)throw new Error(name+' differs from actual pure types');}else fs.writeFileSync(file,content);
 process.stdout.write(`${check?'Verified':'Generated'} ${name}, ${Buffer.byteLength(content)} bytes\n`);
}
