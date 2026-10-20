// Exact, same-case SQLite/JWT/ASGI exports; never invent SKU identity or live flags.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),check=process.argv.includes('--check');
for(const [name,file,sha] of [
 ['input','/tmp/hoim-supply-input-ui-actual-fixtures.json','d76a4a1f510b3621e0fb6c338bfc2fea3b4c23dbc1ec743ef0134f94a46932ec'],
 ['input-complete','/tmp/hoim-supply-input-complete-ui-actual-fixtures.json','c0048578dbbfcb37fec55509e93179b983654c317604a5e3b4cd7a325493786b'],
]){
 const bytes=fs.readFileSync(file),actual=crypto.createHash('sha256').update(bytes).digest('hex');
 if(actual!==sha)throw new Error('Actual export changed: '+file);
 const target=path.join(root,'e2e/fixtures/supply-series',name+'.json');
 if(check){if(!fs.readFileSync(target).equals(bytes))throw new Error('Fixture differs from actual export: '+target);}else fs.writeFileSync(target,bytes);
 console.log(name+': '+bytes.length+'B exact SHA '+actual);
}
