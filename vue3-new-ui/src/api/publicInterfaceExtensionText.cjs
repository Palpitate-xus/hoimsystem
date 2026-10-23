/* Exact unchanged public UI strings for the four new domain families. */
const pool=require('./publicInterfaceExtensionTextPool.json');
module.exports=function publicInterfaceExtensionText(index){
  if(!Number.isSafeInteger(index)||index<0||index>=pool.values.length||typeof pool.values[index]!=='string')throw new Error('Invalid public interface text index');
  return pool.values[index];
};
