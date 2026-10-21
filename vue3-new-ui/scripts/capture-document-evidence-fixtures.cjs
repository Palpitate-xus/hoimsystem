const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'e2e/fixtures/document-evidence'),target=path.join(folder,'actual.json'),manifest=path.join(folder,'manifest.json'),sha=b=>crypto.createHash('sha256').update(b).digest('hex');
if(process.argv[2]==='--check'){
 const bytes=fs.readFileSync(target),record=JSON.parse(fs.readFileSync(manifest,'utf8')),value=JSON.parse(bytes);
 if(bytes.length!==record.fixture_bytes||sha(bytes)!==record.fixture_sha256||value.synthetic_only!==true)throw new Error('Document fixture identity differs');
 process.stdout.write(`Verified actual document router fixture ${bytes.length} bytes\n`);
}else{
 if(process.argv.length!==3)throw new Error('Pass the actual synthetic router packet, or --check');
 const source=fs.readFileSync(process.argv[2]),value=JSON.parse(source);if(value.synthetic_only!==true)throw new Error('Only synthetic actual DTOs');
 const content=Buffer.from(JSON.stringify(value)+'\n');fs.mkdirSync(folder,{recursive:true});fs.writeFileSync(target,content);fs.writeFileSync(manifest,JSON.stringify({scope:'Actual synthetic independent router/JWT/SQLite lifecycle, no model extraction or main mounting',origin_artifact:path.resolve(process.argv[2]),origin_bytes:source.length,origin_sha256:sha(source),fixture_bytes:content.length,fixture_sha256:sha(content)},null,2)+'\n');
 process.stdout.write(`Captured actual document fixture ${content.length} bytes\n`);
}
