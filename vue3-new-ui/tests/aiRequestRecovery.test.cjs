const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const{parse}=require('@vue/compiler-sfc'),parser=require('@babel/parser'),{aiError,aiRequestKey}=require('../src/utils/aiError.cjs');
const code=parse(fs.readFileSync(require.resolve('../src/components/AIAssistant/index.vue'),'utf8')).descriptor.scriptSetup.content;
const names=['stopPolling','startPolling','submit','refreshRun','resetRequestIssue','pauseQuery'];
const source=parser.parse(code,{sourceType:'module'}).program.body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>code.slice(n.start,n.end)).join('\n');
function setup(run={run_id:'test-run',status:'running'}){
 const timers=[],ctx={aiError,aiRequestKey,queuedReplyRequiresRead:()=>false,run:{value:run},requestIssue:{value:null},queryPaused:{value:false},queryLoading:{value:false},recovery:{value:null},submissionBlocks:new Map(),store:{state:{user:{accessToken:'test-session'}}},timer:null,pollVersion:0,selectionVersion:0,submitting:{value:false},dedicatedLifecycle:{value:false},featureKey:{value:'synthetic'},selected:{value:{scope:'input'}},patientId:{value:null},encounterRef:{value:''},preview:{value:false},canPreview:{value:false},buildTaskInput:()=>({question:'synthetic'}),captureSupport:()=>({}),supportCurrent:()=>true,acceptSupportRun:async()=>true,expandQueuedReply:async v=>v,requestedRunMatches:(v,id)=>v.run_id===id,clearUnavailableSupport:()=>{},clearTimeout:t=>{if(t)t.active=false},setTimeout:(fn,delay)=>{const t={fn,delay,active:true};timers.push(t);return t},getAIRun:async()=>{throw {isAxiosError:true,code:'ERR_NETWORK'}},createAIRun:async()=>{throw {isAxiosError:true,code:'ERR_NETWORK'}}};
 for(const k of ['codingLifecycle','supportLifecycle','sofaLifecycle','rosterLifecycle','bedLifecycle','surgeryLifecycle','supplyLifecycle','nativeInventoryLifecycle'])ctx[k]={value:false};
 Object.defineProperty(ctx,'busy',{value:{get value(){return ['queued','running'].includes(ctx.run.value?.status)}}});vm.createContext(ctx);vm.runInContext(source,ctx);return{ctx,timers};
}
test('poll failure pauses queries while preserving true running status and GET recovery never resubmits',async()=>{
 const{ctx,timers}=setup();let writes=0;ctx.createAIRun=async()=>{writes++};ctx.startPolling();const timer=timers.find(t=>t.active);timer.active=false;await timer.fn();
 assert.equal(ctx.run.value.status,'running');assert.equal(ctx.queryPaused.value,true);assert.match(ctx.requestIssue.value.message,/状态查询暂停/);assert.equal(timers.filter(t=>t.active).length,0);
 ctx.getAIRun=async()=>({data:{run_id:'test-run',status:'succeeded'}});await ctx.refreshRun();assert.equal(ctx.run.value.status,'succeeded');assert.equal(ctx.queryPaused.value,false);assert.equal(ctx.requestIssue.value,null);assert.equal(writes,0);
});
test('lost POST acknowledgement blocks identical manual resubmission and removes the old success card',async()=>{
 const{ctx}=setup({run_id:'old',status:'succeeded'});let writes=0;ctx.createAIRun=async()=>{writes++;throw {isAxiosError:true,code:'ERR_NETWORK'}};
 await ctx.submit();assert.equal(ctx.run.value,null);assert.match(ctx.requestIssue.value.message,/提交结果尚未确认/);ctx.run.value={run_id:'previous-different-result',status:'succeeded'};await ctx.submit();assert.equal(writes,1);assert.equal(ctx.run.value,null);assert.equal(ctx.recovery.value.runId,null);
 ctx.buildTaskInput=()=>({question:'changed explicitly'});await ctx.submit();assert.equal(writes,2);
});
test('known create acknowledgement survives follow-up read failure and continues only the accepted task',async()=>{
 const{ctx}=setup(null);let writes=0;ctx.createAIRun=async()=>{writes++;return{data:{run_id:'accepted',status:'queued'}}};ctx.expandQueuedReply=async()=>{throw {isAxiosError:true,code:'ERR_NETWORK'}};
 await ctx.submit();assert.equal(ctx.recovery.value.runId,'accepted');assert.match(ctx.requestIssue.value.message,/任务已经创建/);await ctx.submit();assert.equal(writes,1);
 ctx.getAIRun=async id=>{assert.equal(id,'accepted');return{data:{run_id:id,status:'failed',error_code:'PROVIDER_TIMEOUT'}}};await ctx.refreshRun();assert.equal(ctx.run.value.status,'failed');assert.equal(ctx.submissionBlocks.size,0);assert.equal(ctx.recovery.value,null);assert.equal(writes,1);
});
for(const status of [401,403])test(`query ${status} removes inaccessible results and has a distinct reason`,async()=>{
 const{ctx}=setup();ctx.getAIRun=async()=>{throw {response:{status}}};await ctx.refreshRun();assert.equal(ctx.run.value,null);assert.match(ctx.requestIssue.value.message,status===401?/重新登录/:/操作权限/);
});
test('a stale polling failure cannot replace a later selected task or message',async()=>{
 const{ctx,timers}=setup();let release;ctx.getAIRun=()=>new Promise((_,reject)=>{release=reject});ctx.startPolling();const pending=timers.find(t=>t.active).fn();ctx.stopPolling();ctx.run.value={run_id:'new',status:'succeeded'};release({code:'ERR_NETWORK'});await pending;assert.equal(ctx.run.value.run_id,'new');assert.equal(ctx.requestIssue.value,null);
});

test('protected receipt recovery rechecks the original acknowledgement instead of skipping its scope binding',async()=>{
 const{ctx}=setup(null);const receipt={run_id:'accepted-protected',status:'queued',context_digest:'original'};let writes=0,attempts=0;
 ctx.queuedReplyRequiresRead=()=>true;ctx.createAIRun=async()=>{writes++;return{data:receipt}};
 ctx.expandQueuedReply=async(original,request)=>{assert.strictEqual(original,receipt);assert.equal(request.feature_key,'synthetic');if(++attempts===1)throw {isAxiosError:true,code:'ERR_NETWORK'};return{...receipt,status:'succeeded'}};
 ctx.getAIRun=()=>{throw Error('Receipt proof must not be bypassed')};await ctx.submit();await ctx.refreshRun();assert.equal(ctx.run.value.status,'succeeded');assert.equal(attempts,2);assert.equal(writes,1);
});
test('a created but unverifiable task remains protected against identical resubmission',async()=>{
 const{ctx}=setup(null);let writes=0;ctx.createAIRun=async()=>{writes++;return{data:{run_id:'created',status:'queued'}}};ctx.acceptSupportRun=async()=>false;
 await ctx.submit();assert.equal(ctx.recovery.value.runId,'created');await ctx.submit();assert.equal(writes,1);
});
test('an explicit rejected POST is reported without falsely locking a task that was not created',async()=>{
 const{ctx}=setup(null);ctx.createAIRun=async()=>{throw {response:{status:422,data:{detail:'请先补齐资料。'}}}};await ctx.submit();assert.equal(ctx.submissionBlocks.size,0);assert.equal(ctx.requestIssue.value.message,'请先补齐资料。');assert.equal(ctx.recovery.value,null);
});

test('opening a different historical task cannot reuse an unrelated unknown submission recovery target',()=>{
 const{ctx}=setup(null);ctx.recovery.value={key:'unknown',runId:null};ctx.pauseQuery({code:'ERR_NETWORK'},'historical-task');assert.equal(ctx.recovery.value.runId,'historical-task');
});
