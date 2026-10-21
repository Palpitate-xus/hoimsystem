const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const input='/tmp/hoim-supply-series-ui-actual-fixtures.json',data=JSON.parse(fs.readFileSync(input,'utf8')),out=path.resolve(__dirname,'../e2e/fixtures/supply-series');
const digest=v=>crypto.createHash('sha256').update(JSON.stringify(v)).digest('hex');
const values={partial:data.cases.partial,complete:Object.fromEntries(['period_request','create_request','preview','draft_ordinary'].map(k=>[k,data.cases.complete[k]]))};
for(const[name,value]of Object.entries(values)){const target=path.join(out,name+'.json'),text=JSON.stringify(value)+'\n';if(process.argv.includes('--check')){if(fs.readFileSync(target,'utf8')!==text)throw new Error(name+' differs from exact actual HTTP/ORM export');}else fs.writeFileSync(target,text);process.stdout.write(`${name}: ${Buffer.byteLength(text)} bytes; exact fragment SHA ${digest(value)}\n`);}
