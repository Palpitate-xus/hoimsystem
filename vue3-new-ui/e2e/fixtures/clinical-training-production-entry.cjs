// production_mock: canonical dist, unchanged same-case mounted Main response
// bytes. Only login/SSE shell and explicitly labelled denial signals are synthetic.
const{expect}=require('@playwright/test');
const{startSupplyProductionServer:startTrainingProductionServer}=require('./supply-production-entry.cjs');
const F=require('./clinical-training-task-packets.cjs').loadTrainingTaskPackets('task-shared-main');
const success=F.groups.succeeded_partial_usage,id=F.source.clinical_training_submission_id;
function actual(method,path){const rows=F.source.packets.filter(r=>r.method===method&&r.path===path&&r.status===200);if(rows.length!==1)throw new Error('Ambiguous actual endpoint '+method+' '+path+' '+rows.length);return rows[0];}
async function setupTrainingProduction(page,server,{role='doctor',pipeline=false}={}){
 const s={seen:[],writes:[],bootstrap:[],unknown:[],errors:[],cssErrors:[],external:[],denySource:false,release:null};let polls=0,phase=success;
 page.on('pageerror',e=>s.errors.push(e.message));page.on('response',r=>{if(new URL(r.url()).pathname.endsWith('.css')&&r.status()>=400)s.cssErrors.push([r.url(),r.status()]);});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-training-production-entry'));
 await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();s.external.push(route.request().url());return route.abort('blockedbyclient');});
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname,m=req.method(),query=Object.fromEntries(url.searchParams);
  if(p==='/api/userInfo'&&m==='POST'){s.bootstrap.push({method:m,path:p,body:req.postDataJSON()});return route.fulfill({status:200,json:{code:200,data:{username:'合成教学生产入口',permissions:role==='super_admin'?['super_admin','admin']:[role],avatar:''}}});}
  if(p==='/api/events/stream'&&m==='GET')return route.fulfill({status:204,body:''});
  s.seen.push({method:m,path:p,query,body:req.postData()});if(m!=='GET')s.writes.push({method:m,path:p,body:req.postDataJSON()});
  if(s.denySource&&p==='/api/ai/clinical-training/submissions/'+id)return route.fulfill({status:403,json:{detail:'Synthetic current-source denial signal after actual local feedback'}});
  let row;
  if(p==='/api/ai/runs/'+success.metadata.run_id&&m==='GET'){phase=pipeline?(++polls===1?F.groups.queued:polls===2?F.groups.running:success):success;row=phase.rows[0];}
  else if(p.startsWith('/api/ai/clinical-training/tasks/'+success.metadata.run_id+'/parts/')&&m==='GET')row=phase.rows.find(r=>r.path===p);
  else if(p==='/api/ai/runs'&&m==='POST')row=F.source.packets.find(r=>r.method==='POST'&&r.path===p);
  else if(p==='/api/ai/runs/'+F.groups.cancelled_inflight_paid_partial.metadata.run_id&&m==='GET'&&role==='super_admin')row=F.source.packets.findLast(r=>r.path===p&&r.method==='GET'&&r.actor==='author'&&r.status===200);
  else{const rows=F.source.packets.filter(r=>r.method===m&&r.status===200&&(r.path===p+url.search||r.path===p));row=rows[0];}
  if(!row){s.unknown.push({method:m,path:p,query});return route.fulfill({status:599,json:{detail:'No actual same-case endpoint registered'}});}
  if(m!=='GET')expect(req.postDataJSON()).toEqual(row.request);
  await route.fulfill({status:row.status,contentType:'application/json',body:row.body,headers:row.wire_headers});
 });return s;
}
async function completeTrainingPractice(page){
 await page.getByRole('button',{name:'读取当前已发布课程',exact:true}).click();
 const published=F.data(actual('GET','/api/ai/clinical-training/published-lessons')).items,review=actual('POST','/api/ai/clinical-training/submissions').request.review_id,index=published.findIndex(x=>x.review_id===review);expect(index).toBeGreaterThanOrEqual(0);
 await page.getByRole('button',{name:'核对完整题面',exact:true}).nth(index).click();await expect(page.getByLabel('无答案完整公开题面',{exact:true})).toBeVisible();expect(await page.locator('body').innerText()).not.toContain('PRIVATE_REVIEWED_RATIONALE_SENTINEL');
 const source=success.parts.source.value;for(const answer of source.submission.answers){const i=source.lesson.questions.findIndex(q=>q.question_id===answer.question_id),q=source.lesson.questions[i];for(const selected of answer.selected_option_ids){await page.getByLabel('题目'+(i+1),{exact:true}).getByText(q.options.find(x=>x.option_id===selected).text,{exact:true}).click();}}
 await page.getByText('我明确提交本课程全部题目；空选表示本次明确未作答',{exact:true}).click();await page.getByRole('button',{name:'提交本地练习并取得实际回执',exact:true}).click();await expect(page.getByLabel('实际提交后的固定练习反馈')).toContainText('PRIVATE_REVIEWED_RATIONALE_SENTINEL');await expect(page.getByText('已核对本人实际提交：'+id,{exact:true})).toBeVisible();
}
async function chooseTrainingObjective(page){const select=page.getByRole('combobox',{name:'本次明确教学目标',exact:true});await select.press('ArrowDown');await page.getByRole('option',{name:'解释本次已提交练习与审核答案的相符、不同和明确未作答项',exact:true}).click();}
async function assertTrainingStyles(page,button){await expect(button).toBeVisible();expect(['flex','inline-flex']).toContain(await button.evaluate(e=>getComputedStyle(e).display));expect(await button.evaluate(e=>getComputedStyle(e).borderTopStyle)).toBe('solid');expect(await page.evaluate(()=>Array.from(document.styleSheets).some(s=>s.href&&new URL(s.href).origin===location.origin&&new URL(s.href).pathname.endsWith('.css')))).toBe(true);}
function checkedTrainingProduction(s){expect(s.bootstrap).toEqual([{method:'POST',path:'/api/userInfo',body:{accesstoken:'synthetic-training-production-entry'}}]);expect(s.unknown).toEqual([]);expect(s.errors).toEqual([]);expect(s.cssErrors).toEqual([]);expect(s.external).toEqual([]);expect(s.seen.some(x=>/service-options|operational-context|\/ai\/patients|\/ai\/encounters/u.test(x.path))).toBe(false);expect(s.writes.every(x=>x.path==='/api/ai/clinical-training/submissions'||x.path==='/api/ai/runs'||x.path.endsWith('/feedback'))).toBe(true);}
module.exports={F,success,id,actual,startTrainingProductionServer,setupTrainingProduction,completeTrainingPractice,chooseTrainingObjective,assertTrainingStyles,checkedTrainingProduction};
