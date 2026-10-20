const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),directory=path.join(root,'e2e/fixtures/surgery-synthetic'),check=process.argv.includes('--check');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check is supported');
const inputs=[['sources.json','/tmp/hoim-surgery-source-ui-real-fixtures.json'],['providers.json','/tmp/hoim-surgery-provider-real-asgi-fixtures.json'],['sources-eight-kind.json','/tmp/hoim-surgery-eight-source-ui-real-fixtures.json'],['providers-eight-kind.json','/tmp/hoim-surgery-provider-eight-kind-real-asgi-fixtures.json']];
const provenance=[];
for(const[name,origin]of inputs){
 const raw=fs.readFileSync(origin),value=JSON.parse(raw),text=JSON.stringify(value)+'\n',target=path.join(directory,name);
 if(check)assert.deepStrictEqual(JSON.parse(fs.readFileSync(target,'utf8')),value,'Actual exported DTO must be reproduced exactly');
 else{fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(target,text);}
 provenance.push({fixture:name,actual_export:origin,bytes:raw.length,sha256:crypto.createHash('sha256').update(raw).digest('hex')});
}
const text=JSON.stringify({scope:'Actual synthetic source ORM/services/router-function outputs, and separate real JWT/ASGI admin metadata replies. Source export is not HTTP or native inference; browser tests intercept these exact DTOs. No hand-edited status, UUID, original value or hash.',origins:provenance},null,2)+'\n',target=path.join(directory,'provenance.json');
if(check)assert.equal(fs.readFileSync(target,'utf8'),text);else fs.writeFileSync(target,text);
process.stdout.write(`${check?'Verified':'Copied'} ${inputs.length} actual synthetic DTO exports; old seven-kind originals retained\n`);
