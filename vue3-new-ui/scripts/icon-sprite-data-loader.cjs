/* Only the checked-in, generated and licensed complete icon vector is accepted. */
const path=require('node:path');
const crypto=require('node:crypto');
const {encodeStaticJson,emitStaticJson}=require('./public-static-data.cjs');
const root=path.resolve(__dirname,'..');
function iconSpriteDataLoader(source){
 if(path.resolve(this.resourcePath)!==path.join(root,'src/assets/element-plus-icon-gallery.svg'))throw Error('Icon vector file is not allowlisted');
 this.cacheable();
 const bytes=Buffer.isBuffer(source)?source:Buffer.from(source,'utf8');
 const svg=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
 const manifest=require('../src/api/iconGallery.json');
 const sha=crypto.createHash('sha256').update(bytes).digest('hex');
 if(sha!==manifest.sprite_sha256||manifest.names.length!==293)throw Error('Complete original icon vector differs from generated manifest');
 const expression=emitStaticJson(this,encodeStaticJson(JSON.stringify({svg}))).replace(/^module\.exports = /,'').replace(/;$/,'');
 const reader=this.utils.contextify(this.context,path.join(root,'src/components/staticIconSprite.cjs'));
 return `module.exports=require(${JSON.stringify(reader)}).registerStaticIconSprite(${expression},${JSON.stringify(sha)},${manifest.names.length});`;
}
iconSpriteDataLoader.raw=true;
module.exports=iconSpriteDataLoader;
