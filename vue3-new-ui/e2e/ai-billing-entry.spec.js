const{test}=require('@playwright/test');
const{checkInpatientBillingEntry,checkOutpatientBillingEntry}=require('./fixtures/charge-business-entry.cjs');
// Updated native #69 contract: actual admission and complete published Case.
// Historical outpatient task inspection remains a separate read path.
test('住院费用AI明确选择完整账目与真实住院，不触发结算或退费',async({page})=>checkInpatientBillingEntry(page));
test('门诊费用页明确提示住院原件范围，不提交不兼容的旧LLM账务输入',async({page})=>checkOutpatientBillingEntry(page));
