const test=require('node:test'),assert=require('node:assert/strict');
const{aiError,aiRequestKey}=require('../src/utils/aiError.cjs');
test('authorization failures distinguish expired login from insufficient permission',()=>{
 assert.equal(aiError({response:{status:401,data:{detail:'private'}}}).message,'登录已失效，请重新登录。');
 assert.equal(aiError({response:{status:403,data:{detail:'private'}}}).message,'当前账号没有此项操作权限，请联系管理员调整授权。');
 assert.equal(aiError({response:{status:403}}).uncertain,false);
});
test('safe backend messages take precedence over Axios implementation text',()=>{
 const error={isAxiosError:true,message:'Request failed with status code 503',response:{status:503,data:{detail:'服务维护中，请稍后查询。'}}};
 assert.equal(aiError(error).message,'服务维护中，请稍后查询。');
 assert.equal(aiError(error).uncertain,true);
});
test('binary API failures decode only structured safe messages',()=>{
 const data=new TextEncoder().encode(JSON.stringify({msg:'当前来源已变化，请重新核对。'})).buffer;
 assert.equal(aiError({response:{status:409,data}}).message,'当前来源已变化，请重新核对。');
 assert.equal(aiError({isAxiosError:true,message:'Request failed with status code 502',response:{status:502,data:new TextEncoder().encode('invalid upstream HTML')}}).message,'本次请求未完成，请稍后重试。');
});
test('provider HTTP and attempt diagnostics remain separate from the readable failure',()=>{
 const original=Object.freeze({error_code:'PROVIDER_HTTP_ERROR',error_message:'模型服务返回 HTTP 429，尝试 3/3'});
 const issue=aiError(original);
 assert.equal(issue.message,original.error_message);
 assert.equal(issue.details,'PROVIDER_HTTP_ERROR · HTTP 429 · 尝试 3/3');
 assert.equal(original.error_message,'模型服务返回 HTTP 429，尝试 3/3');
 for(const status of ['401','403'])assert.match(aiError({...original,error_message:`HTTP ${status}`}).message,/密钥与授权/);
});
test('technical exceptions and credential-bearing upstream text never become visible messages',()=>{
 for(const raw of ['Network Error','Request failed with status code 500','上游 https://private.example/v1 使用 sk-secret-private','模型 Bearer secret 拒绝访问','Traceback 模型出错']){
  const issue=aiError({error_message:raw});assert.equal(issue.message,'本次请求未完成，请稍后重试。');assert.equal(issue.details,'');
 }
});
test('known terminal failures are actionable without changing the task object',()=>{
 for(const code of ['PROVIDER_TIMEOUT','PROVIDER_UNAVAILABLE','INVALID_PROVIDER_RESPONSE','INCOMPLETE_RESPONSE','WORKER_INTERRUPTED','RESULT_STORAGE_ERROR'])assert.notEqual(aiError({error_code:code}).message,'本次请求未完成，请稍后重试。');
 assert.equal(aiError({code:'ETIMEDOUT',isAxiosError:true}).message,'请求超时，请先核对任务记录。');
 assert.equal(aiError({code:'ERR_BLOCKED_ORIGIN'}).uncertain,false);
});

test('submission fingerprints retain scope and values while ignoring JSON object property order',()=>{
 assert.equal(aiRequestKey('one',{feature:'x',input:{a:1,b:2}}),aiRequestKey('one',{input:{b:2,a:1},feature:'x'}));
 assert.notEqual(aiRequestKey('one',{input:{a:1}}),aiRequestKey('two',{input:{a:1}}));
 assert.notEqual(aiRequestKey('one',{input:{a:null}}),aiRequestKey('one',{input:{}}));
});

for(const [code,message]of[
 ['PROVIDER_HTTP_ERROR','模型服务拒绝请求（HTTP 400，已尝试 1/3 次），请检查模型参数和接口格式。'],
 ['PROVIDER_HTTP_ERROR','模型服务账单异常（HTTP 402，已尝试 1/3 次），请管理员核对账单。'],
 ['INVALID_PROVIDER_RESPONSE','模型未返回合格的结构化输出，请检查结构化输出设置。'],
 ['INCOMPLETE_RESPONSE','模型输出未完成，请管理员提高输出上限后重新提交。'],
])test(`safe backend guidance for ${code} takes priority over generic code mappings: ${message}`,()=>{
 assert.equal(aiError({error_code:code,error_message:message}).message,message);
 assert.equal(aiError({response:{status:503,data:{detail:message,error_code:code}},message:'Request failed with status code 503',isAxiosError:true}).message,message);
});
test('safe guidance is bounded, and application authentication status still takes priority',()=>{
 assert.equal(aiError({error_code:'PROVIDER_TIMEOUT',error_message:'服务维护中。'.repeat(120)}).message.length,500);
 assert.equal(aiError({response:{status:401,data:{detail:'模型服务账单异常。'}}}).message,'登录已失效，请重新登录。');
});
