<template>
  <section v-if="member" :aria-label="`SOFA逐源判读 ${member.member_key}`">
    <p class="hash">{{ member.member_key }} · {{ member.temporal_role === 'prefix' ? '日前必要给药前缀' : '日内原记录' }}<br />原内容 {{ member.content_hash }}<br />原治理 {{ member.governance_hash }}</p>
    <p v-if="!member.eligible">该原件当前存在排除事项：{{ member.exclusion_reasons.join('、') }}。原件仍在完整清单内，判读不删除原事实。</p>
    <el-table :data="facts" aria-label="SOFA当前原件原量与真实时钟">
      <el-table-column prop="label" label="原事实" /><el-table-column prop="value" label="原值或原状态" /><el-table-column prop="unit" label="原单位" /><el-table-column prop="clock" label="真实原时刻" min-width="230" />
    </el-table>
    <p>原观察与登记分别保留。以下为医生当前回顾判读，不回填为旧截止时点已知。</p>
    <review-fields :model-value="modelValue" :definition="definitions[member.kind]" prefix="SOFA逐源" @update:model-value="emit('update:modelValue',$event)" />
    <details><summary>院内核对完整原件与关联依据</summary><p>完整原件用于本院来源核对；模型只接收固定公开投影。</p><pre>{{ JSON.stringify(member.full_source,null,2) }}</pre></details>
  </section>
</template>
<script setup>
import { computed } from "vue";
import ReviewFields from "./ReviewFields.vue";
const props=defineProps({member:{type:Object,default:null},modelValue:{type:Object,required:true}}),emit=defineEmits(["update:modelValue"]);
const definitions={laboratory:"LaboratoryReview",map:"MapReview",respiratory_support:"RespiratorySupportReview",arterial_pair:"ArterialPairReview",vasoactive:"VasoactiveReview",gcs:"GcsReview",urine:"UrineReview"};
const missing=value=>value===null||value===undefined?"未知":typeof value==="boolean"?(value?"true":"false"):String(value);
const facts=computed(()=>{const member=props.member,source=member?.full_source;if(!source)return[];const p=source.payload||{},rows=[];
 const add=(label,value,unit="",clock="")=>rows.push({label,value:missing(value),unit,clock});
 const quantity=(label,q,clock="")=>add(label,q?.value??`未测（${q?.absent_reason||"unknown"}）`,q?.unit||"",clock);
 const lab=(label,row)=>{const o=row?.snapshot?.original?.observation;add(label,o?.value_num??o?.value_text??"未测",o?.unit||"",row?.collected_at_utc||"");};
 if(member.kind==="laboratory"){add("受控原项目",source.snapshot?.mapping?.analyte_key);lab("原检验结果",source);add("系统登记／可用",source.registered_at,"",source.available_at);}
 if(member.kind==="map"){quantity("原平均动脉压",p.map,p.observed_at);add("原测量方法",p.measurement_method);}
 if(member.kind==="respiratory_support"){add("原呼吸支持模式",p.delivery_mode);add("原连续性确认",p.continuity_confirmed);}
 if(member.kind==="arterial_pair"){const r=source.reference_snapshots||{};lab("明确原PaO₂",r.pao2);quantity("明确原FiO₂",r.fio2?.payload?.measurements?.fio2,r.fio2?.observed_at);add("原关联支持模式",r.support?.payload?.delivery_mode,"",r.support?.payload?.start_at);for(const key of ["arterial_sample_confirmed","same_sampling_state_confirmed","fio2_applicability_confirmed"])add(key,p[key]);}
 if(member.kind==="vasoactive"){const r=source.reference_snapshots||{},d=p.dose_input||{};add("原映射药物",r.drug_mapping?.drug_key);add("原药物质量口径",r.drug_mapping?.active_moiety_basis);add("原剂量输入方式",d.mode);for(const key of ["rate","concentration","pump_rate"])if(d[key])quantity(key,d[key]);if(r.weight)quantity("明确原体重",r.weight.payload?.measurements?.body_weight,r.weight.observed_at);add("原体重整段适用声明",d.weight_applicability_confirmed);add("原物理流命名空间",p.stream_identity?.source_namespace);add("原物理流标识",p.stream_identity?.external_stream_id);add("原连续性确认",p.continuity_confirmed);}
 if(member.kind==="gcs"){for(const key of ["eye","verbal","motor"]){const c=p.components?.[key];add({eye:"睁眼E",verbal:"言语V",motor:"运动M"}[key],c?.score??(c?.absent_reason==="not_testable"?"NT（不能测试）":"未记录"),"",source.observed_at);}add("原显式锚点",p.anchor_point?.observation_id??"未关联");add("原锚点当前性",source.anchor_current);}
 if(member.kind==="urine"){add("原收集量",p.volume_ml??`未测（${p.absent_reason||"unknown"}）`,"mL");add("原收集完整性",p.collection_completeness);add("原患者总量声明",p.patient_total);add("原结束",source.end_at);}
 for(const key of ["observed_at","start_at","verified_until_at","ended_at"])if(p[key]!==undefined)add({observed_at:"原观察",start_at:"原开始",verified_until_at:"原核实至",ended_at:"原已结束"}[key],p[key]);
 if(source.start_at)add("原开始",source.start_at);add("原系统登记",source.recorded_at??source.registered_at);return rows;});
</script>
<style scoped>.hash,pre{overflow-wrap:anywhere;white-space:pre-wrap}p{line-height:1.6}</style>
