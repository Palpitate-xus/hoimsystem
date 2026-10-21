import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
export function useOperationsSession(props,clear){
 const store=useStore(),kept=ref(true);let epoch=0;
 const roles=computed(()=>store.state.user?.permissions),role=computed(()=>{const r=roles.value;return Array.isArray(r)&&r.length&&new Set(r).size===r.length&&r.every(x=>['admin','super_admin'].includes(x))?(r.includes('super_admin')?'super_admin':'admin'):null;});
 const fingerprint=computed(()=>JSON.stringify([store.state.user?.accessToken??null,store.state.user?.username??null,roles.value,props.active,props.configRevision??null,props.governance??false,props.auditOnly??false,kept.value]));
 const allowed=computed(()=>!!store.state.user?.accessToken&&!!role.value&&props.active!==false&&kept.value&&(!(props.governance||props.auditOnly)||role.value==='super_admin'));
 const invalidate=()=>{epoch++;clear();};
 const ticket=()=>({epoch,fingerprint:fingerprint.value}),current=t=>allowed.value&&t.epoch===epoch&&t.fingerprint===fingerprint.value;
 watch(fingerprint,invalidate,{flush:'sync'});onDeactivated(()=>{kept.value=false;});onActivated(()=>{kept.value=true;});onBeforeUnmount(()=>{kept.value=false;invalidate();});
 return{allowed,role,ticket,current,invalidate,advance:()=>{epoch++;},store};
}
