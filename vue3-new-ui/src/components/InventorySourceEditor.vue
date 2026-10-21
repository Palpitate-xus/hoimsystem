<template>
  <el-form label-position="top" @submit.prevent>
    <p>独立实盘、技术库存采集、未来出库情景与完整采购候选分别登记。未填写保持未填写，null 与原数值零分开；不自动确认单位、覆盖、效期或专业状态。</p>
    <el-form-item label="明确绑定的受审原计数单位"><el-select :model-value="modelValue.unit_definition_id===null?'__none__':modelValue.unit_definition_id" aria-label="明确绑定的受审原计数单位" placeholder="明确选择原单位或未知" @update:model-value="emit('unit-change',$event)"><el-option value="__none__" label="明确原单位绑定未知（null）" /><el-option v-for="u in units" :key="u.source_record_id" :value="u.source_record_id" :label="u.payload.original_unit_text+' · '+u.source_record_id" /></el-select></el-form-item>
    <p v-if="selectedUnit">原计数单位：{{ selectedUnit.payload.original_unit_text }}。选择只绑定原件，不自动确认本条每个原量的单位。</p>
    <el-button v-if="selectedUnit" @click="copyUnitText">明确将所选原单位文字填入本条已有数量项</el-button>
    <SurgeryFields :schema="mainSchema" :root="root" :field-labels="labels" :lookups="lookups" label="本条原始资料" :model-value="payload" @update:model-value="replace" />
    <template v-if="kind==='inventory_observation'">
      <p>独立实盘必须填写真实原观察UTC6；技术采集没有物理观察时刻，须明确选择 observed_at 为空。</p>
      <el-button @click="set('lots',[])">明确实盘批次集合为空</el-button><el-button @click="addPhysical">添加实际观察批次</el-button>
      <div v-for="index in indices(payload.lots,lotPage)" :key="payload.lots[index].lot_id"><SurgeryFields :schema="lotSchema" :root="root" :field-labels="labels" :lookups="lookups" :fixed-keys="['lot_id']" :label="'实际观察批次 第'+(index+1)+'项'" :model-value="payload.lots[index]" @update:model-value="value=>set('lots',payload.lots.map((x,i)=>i===index?value:x))" /><el-button @click="set('lots',payload.lots.filter((_,i)=>i!==index))">移除此观察批次</el-button></div>
      <el-pagination v-if="payload.lots?.length>20" v-model:current-page="lotPage" :page-size="20" :total="payload.lots.length" layout="prev,pager,next,total" />
    </template>
    <template v-else-if="kind==='future_quantity_scenario'">
      <el-button :disabled="!canBuildDays" @click="buildDays">按明确时区和日期生成空白日表</el-button><p>真实日界由IANA时区生成，原情景数量和核实状态仍须逐项填写。修改时区或日期后须重新生成。</p>
      <SurgeryFields v-if="payload.days" :schema="daysSchema" :root="root" :field-labels="labels" :lookups="lookups" :fixed-keys="['date','day_start_at','day_end_at']" :locked-arrays="['days']" field-key="days" label="全部未来业务日原量" :model-value="payload.days" @update:model-value="value=>set('days',value)" />
    </template>
    <template v-else>
      <p>每个候选保留整份采购单及所有收货批次。没有订单的基线也必须明确登记并填写原固定费用，系统不自动补零。</p>
      <el-button @click="set('orders',[])">明确本候选没有采购单</el-button><el-button @click="addOrder">添加完整采购单</el-button>
      <div v-for="index in indices(payload.orders,orderPage)" :key="payload.orders[index].order_id">
        <SurgeryFields :schema="orderSchema" :root="root" :field-labels="labels" :lookups="lookups" :fixed-keys="['order_id']" :label="'原完整采购单 第'+(index+1)+'项'" :model-value="payload.orders[index]" @update:model-value="value=>updateOrder(index,value)" />
        <el-button @click="addReceipt(index)">为第{{ index+1 }}份采购单添加原收货批次</el-button><el-button @click="set('orders',payload.orders.filter((_,i)=>i!==index))">移除此完整采购单</el-button>
        <div v-for="j in indices(payload.orders[index].lines,receiptPages[payload.orders[index].order_id]||1)" :key="payload.orders[index].lines[j].lot_id"><SurgeryFields :schema="receiptSchema" :root="root" :field-labels="labels" :lookups="lookups" :fixed-keys="['lot_id']" :label="'采购单'+(index+1)+'收货批次'+(j+1)" :model-value="payload.orders[index].lines[j]" @update:model-value="value=>updateLine(index,j,value)" /><el-button @click="updateOrder(index,{...payload.orders[index],lines:payload.orders[index].lines.filter((_,i)=>i!==j)})">移除此收货批次</el-button></div>
        <el-pagination v-if="payload.orders[index].lines?.length>20" :current-page="receiptPages[payload.orders[index].order_id]||1" :page-size="20" :total="payload.orders[index].lines.length" layout="prev,pager,next,total" @current-change="value=>receiptPages[payload.orders[index].order_id]=value" />
      </div>
      <el-pagination v-if="payload.orders?.length>20" v-model:current-page="orderPage" :page-size="20" :total="payload.orders.length" layout="prev,pager,next,total" />
    </template>
    <el-form-item label="实际药师本人专业确认"><el-select :model-value="payload.professional_attestation?.status" aria-label="实际药师本人专业确认" placeholder="明确选择，未选择不默认为已确认" @update:model-value="signature"><el-option value="unknown" label="专业确认未知，仅登记原件" /><el-option v-if="canConfirmProfessional&&professionalSignerUserId" value="confirmed" :label="'当前实际药师本人 #'+professionalSignerUserId+' 明确确认'" /></el-select></el-form-item>
    <el-form-item v-if="payload.professional_attestation?.status==='confirmed'" label="药师本人专业确认依据"><el-input type="textarea" :model-value="payload.professional_attestation.basis_note" aria-label="药师本人专业确认依据" @update:model-value="value=>set('professional_attestation',{...payload.professional_attestation,basis_note:value})" /></el-form-item>
    <p>明确已核实或覆盖完整必须由当前药师本人签署；技术角色仅可登记未知或未核实。分页仅改变显示，提交保留全部原始条目。</p>
  </el-form>
</template>
<script setup>
import {computed,ref} from 'vue';
import SurgeryFields from './AISurgerySources/SurgeryFields.vue';
import {inventorySourceSchema} from '@/api/ai/inventorySources';
import {supplyDayBounds} from '@/api/ai/supplySources';
const props=defineProps({kind:{type:String,required:true},modelValue:{type:Object,required:true},units:{type:Array,default:()=>[]},selectedUnit:{type:Object,default:null},canConfirmProfessional:Boolean,professionalSignerUserId:{type:Number,default:null}}),emit=defineEmits(['update:modelValue','unit-change']),lotPage=ref(1),orderPage=ref(1),receiptPages=ref({});
const payload=computed(()=>props.modelValue.payload||{}),root=computed(()=>inventorySourceSchema('SourceCreate'));
const labels={kind:'本条原件种类',method:'原库存观察方法',observed_at:'独立实盘原观察完成UTC6',scope_review:'原实盘范围核实',coverage:'原完整覆盖声明',coverage_basis_note:'原完整覆盖依据',lots:'全部实际观察批次',lot_id:'本条批次技术标识',original_lot_key:'实际原批次引用文字',quantity:'原批次数量',declared_total_quantity:'原明确实盘总量',frozen_quantity:'原冻结数量',original_unit_text:'原数量单位文字',unit_review:'原单位明确核实',valid_through:'原效期最后有效日',expiry_review:'原效期核实',frozen_review:'原冻结量核实',physical_reconciliation:'原实盘批次与总量对账',reconciliation_basis_note:'原实盘对账依据',legacy_reconciliation:'已审阅的原库存全集对账',legacy_reconciliation_basis_note:'原库存全集对账依据',legacy_quantity_unit_review:'原目录与批次每单位口径对应核实',legacy_quantity_unit_basis_note:'原目录与批次口径对应依据',definition_basis_note:'本条原量定义与业务依据',timezone:'明确IANA业务时区',date_from:'明确未来业务首日',date_to:'明确未来业务末日',basis:'未来情景原依据类型',quantity_definition:'未来情景数量口径',required_quantity:'原情景物理出库量',date:'原业务日期',day_start_at:'原业务日开始UTC6',day_end_at:'原业务日结束UTC6',completeness:'完整候选覆盖声明',completeness_basis_note:'完整候选覆盖依据',plan_fixed_fee:'原整份候选固定费用',order_id:'本条采购单技术标识',original_order_key:'实际原采购单引用文字',order_fixed_fee:'原整份采购单固定费用',lines:'全部原收货批次',arrival_date:'原明确到货业务日期',unit_price:'原每一计数单位的价格',price_basis_review:'原每单位计价核实',price_basis_note:'原每单位计价依据',currency_text:'原明确币种文字',original_cost_unit_text:'原明确计价单位文字'};
function resolve(v){return v?.$ref?root.value.$defs[v.$ref.split('/').at(-1)]:v;}
const payloadSchema=computed(()=>root.value.properties.payload.oneOf.map(resolve).find(s=>s.properties.kind.const===props.kind));
function without(schema,omit){const value=JSON.parse(JSON.stringify(resolve(schema)));for(const key of omit)delete value.properties?.[key];if(value.required)value.required=value.required.filter(k=>!omit.includes(k));if(!props.canConfirmProfessional){const filter=v=>{if(v&&typeof v==='object'){if(Array.isArray(v.enum))v.enum=v.enum.filter(x=>!['confirmed','attested_complete'].includes(x));for(const x of Object.values(v))filter(x);}};filter(value);}return value;}
const lookups=computed(()=>Object.fromEntries(['scope_review','unit_review','expiry_review','frozen_review','price_basis_review','physical_reconciliation','legacy_reconciliation','legacy_quantity_unit_review'].map(k=>[k,[...(props.canConfirmProfessional?[{value:'confirmed',label:'该项由本人明确核实'}]:[]),{value:'not_confirmed',label:'该项未核实'},{value:'unknown',label:'该项核实未知'}]]).concat([['method',[{value:'independent_count',label:'原独立实际盘点'},{value:'legacy_current_capture',label:'原当前账目技术采集，无独立实盘观察时刻'}]]])));
const mainSchema=computed(()=>without(payloadSchema.value,['kind','basis','quantity_definition','professional_attestation','lots','days','orders'])),lotSchema=computed(()=>root.value.$defs.InitialLot),daysSchema=computed(()=>payloadSchema.value.properties.days),orderSchema=computed(()=>without(root.value.$defs.Order,['lines'])),receiptSchema=computed(()=>root.value.$defs.ReceiptLot);
const indices=(rows,page)=>Array.isArray(rows)?rows.map((_,i)=>i).slice((page-1)*20,page*20):[];
function replace(value){emit('update:modelValue',{...props.modelValue,payload:value});}
function set(key,value){replace({...payload.value,[key]:value});}
function signature(status){set('professional_attestation',status==='confirmed'?{status,signer_user_id:props.professionalSignerUserId,basis_note:undefined}:{status,signer_user_id:null,basis_note:null});}
function addPhysical(){const rows=[...(payload.value.lots||[]),{lot_id:crypto.randomUUID()}];set('lots',rows);lotPage.value=Math.ceil(rows.length/20);}
function addOrder(){const rows=[...(payload.value.orders||[]),{order_id:crypto.randomUUID()}];set('orders',rows);orderPage.value=Math.ceil(rows.length/20);}
function updateOrder(i,value){set('orders',payload.value.orders.map((x,j)=>i===j?value:x));}
function addReceipt(i){const order=payload.value.orders[i],lines=[...(order.lines||[]),{lot_id:crypto.randomUUID()}];updateOrder(i,{...order,lines});receiptPages.value[order.order_id]=Math.ceil(lines.length/20);}
function updateLine(i,j,value){const order=payload.value.orders[i];updateOrder(i,{...order,lines:order.lines.map((x,k)=>k===j?value:x)});}
const canBuildDays=computed(()=>{try{const p=payload.value,start=Date.parse(p.date_from+'T00:00:00Z'),end=Date.parse(p.date_to+'T00:00:00Z');if(!Number.isFinite(start)||!Number.isFinite(end)||end<start||end-start>30*86400000)return false;supplyDayBounds(p.date_from,p.timezone);supplyDayBounds(p.date_to,p.timezone);return true;}catch{return false;}});
function buildDays(){if(!canBuildDays.value)return;const p=payload.value,rows=[];for(let d=p.date_from;d<=p.date_to;d=new Date(Date.parse(d+'T00:00:00Z')+86400000).toISOString().slice(0,10)){const[start,end]=supplyDayBounds(d,p.timezone);rows.push({date:d,day_start_at:start,day_end_at:end});}set('days',rows);}
function copyUnitText(){if(!props.selectedUnit)return;const value=JSON.parse(JSON.stringify(payload.value)),text=props.selectedUnit.payload.original_unit_text;function fill(v){if(!v||typeof v!=='object')return;if(Object.hasOwn(v,'value')&&Object.hasOwn(v,'absent_reason')&&!Object.hasOwn(v,'currency_text')&&(Object.hasOwn(v,'unit_review')||Object.hasOwn(v,'original_unit_text')))v.original_unit_text=text;for(const x of Object.values(v))fill(x);}fill(value);replace(value);}
</script>
