const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const input='/tmp/hoim-charge-source-status-legends-ui-real-fixtures.json',raw=fs.readFileSync(input),actual=JSON.parse(raw);
const value={...actual,browser_provenance:{source_path:input,source_sha256:crypto.createHash('sha256').update(raw).digest('hex'),source_bytes:raw.length,scope:'Actual synthetic SQLite Source services and router-function responses. Isolated browser mocks use unchanged DTOs; not real HTTP/backend, model, payment or refund evidence.'}};
assert.deepEqual(JSON.parse(JSON.stringify(value,(k,v)=>k==='browser_provenance'?undefined:v)),actual);
const target=path.resolve(__dirname,'../e2e/fixtures/charge-sources/actual.json'),text=JSON.stringify(value)+'\n';
if(process.argv.includes('--check'))assert.equal(fs.readFileSync(target,'utf8'),text);else{fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text);}
process.stdout.write(`Verified unchanged actual charge lifecycle: ${Buffer.byteLength(text)} bytes\n`);
{
 const input='/tmp/hoim-charge-source-status-legends-mysql-ui-real-fixtures.json',raw=fs.readFileSync(input),actual=JSON.parse(raw);
 const value={...actual,browser_provenance:{source_path:input,source_sha256:crypto.createHash('sha256').update(raw).digest('hex'),source_bytes:raw.length,scope:'Actual private MySQL metadata-backed governed Source functions and FLOAT same-statement witnesses. Isolated browser mocks, not real backend HTTP or model/payment proof.'}};
 assert.deepEqual(JSON.parse(JSON.stringify(value,(k,v)=>k==='browser_provenance'?undefined:v)),actual);
 const target=path.resolve(__dirname,'../e2e/fixtures/charge-sources/actual-mysql.json'),text=JSON.stringify(value)+'\n';if(process.argv.includes('--check'))assert.equal(fs.readFileSync(target,'utf8'),text);else fs.writeFileSync(target,text);
 process.stdout.write(`Verified unchanged actual MySQL charge source: ${Buffer.byteLength(text)} bytes\n`);
}

{
 const input='/tmp/hoim-charge-source-redacted-revoke-ui-real-fixtures.json',raw=fs.readFileSync(input),actual=JSON.parse(raw);
 const value={...actual,browser_provenance:{source_path:input,source_sha256:crypto.createHash('sha256').update(raw).digest('hex'),source_bytes:raw.length,scope:'Actual synthetic SQLite author with operations grant: published then real new zero member, stale redaction, actual author revoke and Super audit. Not HTTP/worker or money evidence.'}};
 assert.deepEqual(JSON.parse(JSON.stringify(value,(k,v)=>k==='browser_provenance'?undefined:v)),actual);
 const target=path.resolve(__dirname,'../e2e/fixtures/charge-sources/actual-redacted-revoke.json'),text=JSON.stringify(value)+'\n';if(process.argv.includes('--check'))assert.equal(fs.readFileSync(target,'utf8'),text);else fs.writeFileSync(target,text);
 process.stdout.write(`Verified actual redacted author revoke: ${Buffer.byteLength(text)} bytes\n`);
}
