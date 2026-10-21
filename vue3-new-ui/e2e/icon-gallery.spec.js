const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const gallery=require('../src/api/iconGallery.json');
const icons=require('@element-plus/icons-vue');
const {createSSRApp,h}=require('vue');
const {renderToString}=require('@vue/server-renderer');
const {startServer,setup,checked}=require('./fixtures/drug-label-production-entry.cjs');
let server,originals;
test.beforeAll(async()=>{server=await startServer();originals=await Promise.all(gallery.names.map(async name=>({name,svg:await renderToString(createSSRApp({render:()=>h(icons[name])}))})))});
test.afterAll(async()=>{try{expect(server.unhandled).toEqual([])}finally{await server.close()}});
test('canonical public vector preserves all 293 installed original paths and exact rasterized geometry',async({page})=>{
 const source=fs.readFileSync(path.resolve(__dirname,'../src/assets/element-plus-icon-gallery.svg'));
 expect(crypto.createHash('sha256').update(source).digest('hex')).toBe(gallery.sprite_sha256);
 const state=await setup(page,server);
 const actual=await page.evaluate(async({originals,sha})=>{
  const sprites=document.querySelectorAll('#hoim-element-plus-icon-sprite');
  if(sprites.length!==1||sprites[0].getAttribute('data-sha256')!==sha)throw Error('Missing uniquely verified original vector');
  const sprite=sprites[0],parser=new DOMParser();
  const expected=originals.map(({name,svg})=>({name,node:parser.parseFromString(svg,'image/svg+xml').documentElement}));
  if(sprite.querySelectorAll('symbol').length!==expected.length)throw Error('Incomplete original symbols');
  const xml=new XMLSerializer();
  for(const {name,node}of expected){
   const symbol=sprite.querySelector('#icon-'+name);
   if(!symbol||symbol.getAttribute('viewBox')!==node.getAttribute('viewBox')||symbol.getAttribute('xml:space')!==node.getAttribute('xml:space')||symbol.childNodes.length!==node.childNodes.length||Array.from(symbol.childNodes).some((child,i)=>!child.isEqualNode(node.childNodes[i])))throw Error('Original geometry differs: '+name);
  }
  const originalBody=expected.map(({node},i)=>{node.setAttribute('x',String(i%16*32));node.setAttribute('y',String(Math.floor(i/16)*32));node.setAttribute('width','32');node.setAttribute('height','32');return xml.serializeToString(node)}).join('');
  const actualBody='<defs>'+Array.from(sprite.querySelectorAll('symbol')).map(node=>xml.serializeToString(node)).join('')+'</defs>'+expected.map(({name},i)=>`<svg x="${i%16*32}" y="${Math.floor(i/16)*32}" width="32" height="32" viewBox="0 0 1024 1024"><use href="#icon-${name}"/></svg>`).join('');
  async function pixels(body){
   const svg='<svg xmlns="http://www.w3.org/2000/svg" width="512" height="608" style="color:#314a67">'+body+'</svg>';
   const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
   try{const image=new Image();image.src=url;await image.decode();const canvas=document.createElement('canvas');canvas.width=512;canvas.height=608;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);return ctx.getImageData(0,0,512,608).data}finally{URL.revokeObjectURL(url)}
  }
  const a=await pixels(originalBody),b=await pixels(actualBody);let different=0,painted=0;for(let i=0;i<a.length;i++){if(a[i]!==b[i])different++;if(i%4===3&&a[i])painted++}
  return {count:expected.length,different,painted};
 },{originals,sha:gallery.sprite_sha256});
 expect(actual.count).toBe(293);expect(actual.different).toBe(0);expect(actual.painted).toBeGreaterThan(10000);checked(state);
});
