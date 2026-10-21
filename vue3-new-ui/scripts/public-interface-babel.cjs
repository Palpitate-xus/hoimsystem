/* Babel-loader's documented result hook keeps its original one-loader contract. */
const loader=require('./public-interface-text-loader.cjs');
module.exports=()=>({
 result(result){
  const context={resourcePath:this.resourcePath,context:this.context,utils:this.utils,cacheable:()=>this.cacheable(),addDependency:name=>this.addDependency?.(name),getOptions:()=>({documentData:true}),emitFile:(...args)=>this.emitFile(...args)};
  const code=loader.call(context,result.code);
  return code===result.code?result:{...result,code,map:null,ast:null};
 }
});
