<template>
  <div class="app-container permission-page">
    <el-alert v-if="!authorized" title="当前账号没有权限管理权限" type="warning" :closable="false" />
    <el-card v-else v-loading="loading">
      <el-tabs v-model="tab" @tab-change="changeTab">
        <el-tab-pane label="用户权限" name="users">
          <div class="page-toolbar">
            <el-select v-model="roleFilter" aria-label="筛选角色" placeholder="全部角色" clearable @change="fetchUsers">
              <el-option v-for="role in roles" :key="role.key" :label="role.label" :value="role.key" />
            </el-select>
            <el-button @click="fetchUsers">刷新用户</el-button>
          </div>
          <el-table :data="users" empty-text="暂无用户">
            <el-table-column prop="user_id" label="用户 ID" width="90" />
            <el-table-column prop="username" label="用户名" min-width="130" />
            <el-table-column label="角色" min-width="120"><template #default="{row}">{{ roleLabel(row.user_role) }}</template></el-table-column>
            <el-table-column label="操作" min-width="310"><template #default="{row}">
              <el-button size="small" :disabled="!manageable(row.user_role)" @click="openPolicy('user', row.user_id)">用户权限</el-button>
              <el-button size="small" :disabled="!accountAllowed(row, 'role')" @click="openRole(row)">修改角色</el-button>
              <el-button size="small" :disabled="!accountAllowed(row, 'password')" @click="resetPassword(row)">重置密码</el-button>
              <el-button size="small" type="danger" :disabled="!accountAllowed(row, 'delete')" @click="deleteUser(row)">删除</el-button>
            </template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="角色权限" name="roles">
          <el-table :data="roles" empty-text="暂无角色">
            <el-table-column prop="label" label="角色" />
            <el-table-column prop="key" label="标识" />
            <el-table-column label="操作" width="140"><template #default="{row}"><el-button size="small" @click="openPolicy('role', row.key)">{{ row.manageable ? '配置权限' : '查看权限' }}</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane v-if="canReadAudit" label="权限审计" name="audit">
          <el-button @click="fetchAudit">刷新记录</el-button>
          <el-table :data="auditRows" max-height="60vh" class="audit-table" empty-text="暂无权限变更记录">
            <el-table-column prop="created_at" label="时间" min-width="180" />
            <el-table-column prop="actor" label="操作人" min-width="100" />
            <el-table-column prop="subject" label="对象" min-width="140" />
            <el-table-column prop="action" label="操作" min-width="130" />
            <el-table-column label="变更摘要" min-width="280"><template #default="{row}"><span class="audit-summary">{{ row.change.summary }}</span></template></el-table-column>
            <el-table-column label="详情" width="110"><template #default="{row}"><el-button size="small" @click="openAudit(row)">查看详情</el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="auditPage" :page-size="20" :total="auditTotal" layout="prev, pager, next, total" @current-change="fetchAudit" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-dialog v-model="auditVisible" title="权限变更详情" width="min(1000px, 94vw)" top="6vh" destroy-on-close>
      <template v-if="auditDetail">
        <p class="audit-meta">#{{ auditDetail.id }} · {{ auditDetail.actor }} · {{ auditDetail.subject }} · {{ auditDetail.created_at }}</p>
        <p>{{ auditDetail.change.summary }}</p>
        <el-tabs v-model="auditView">
          <el-tab-pane label="配置变化" name="changes">
            <div class="audit-content" aria-label="权限配置变化">
              <template v-if="auditDetail.change.before">
                <template v-if="auditDetail.change.explicit">
                  <section v-for="group in auditGroups" :key="group.label"><h4>{{ group.label }}（{{ group.codes.length }} 项）</h4>
                    <div v-for="code in group.codes" :key="code" class="audit-permission"><span>{{ permissionLabels.get(code)?.label || code }}</span><code>{{ permissionLabels.get(code) ? `${permissionLabels.get(code).method} ${permissionLabels.get(code).path}` : code }}</code></div>
                  </section>
                </template>
                <template v-else>
                  <section v-for="side in ['before', 'after']" :key="side"><h4>{{ side === 'before' ? '变更前' : '变更后' }}：{{ auditStrategy(auditDetail.change[side].allowed_permissions) }}</h4>
                    <div v-for="code in auditDetail.change[side].allowed_permissions || []" :key="code" class="audit-permission"><span>{{ permissionLabels.get(code)?.label || code }}</span><code>{{ permissionLabels.get(code) ? `${permissionLabels.get(code).method} ${permissionLabels.get(code).path}` : code }}</code></div>
                  </section>
                </template>
              </template>
              <p v-else>此记录保留原始审计内容。</p>
            </div>
          </el-tab-pane>
          <el-tab-pane label="完整审计原值" name="raw" lazy><pre class="audit-content audit-raw">{{ auditDetail.change.raw }}</pre></el-tab-pane>
        </el-tabs>
      </template>
      <template #footer><el-button @click="auditVisible = false">关闭详情</el-button></template>
    </el-dialog>
    <el-dialog v-model="roleVisible" title="修改用户角色" width="420px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="用户名">{{ currentUser.username }}</el-form-item>
        <el-form-item label="角色"><el-select v-model="newRole" aria-label="新角色"><el-option v-for="role in roles.filter(item => isSuper || item.manageable)" :key="role.key" :label="role.label" :value="role.key" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="roleVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitRole">保存角色</el-button></template>
    </el-dialog>
    <el-drawer v-model="policyVisible" :title="policy ? `${policy.kind === 'role' ? '角色' : '用户'}权限：${policy.label}` : '权限配置'" size="min(900px, 100vw)" destroy-on-close>
      <div v-loading="policyLoading">
        <template v-if="policy">
          <el-alert v-if="conflict" title="权限已被其他管理员修改。请重新加载后保存。" type="warning" :closable="false" />
          <el-form label-width="100px">
            <el-form-item label="权限来源">
              <el-radio-group v-model="inherit" :disabled="!canEdit || saving" aria-label="权限来源"><el-radio :value="true">继承{{ policy.kind === 'user' ? '角色' : '默认' }}权限</el-radio><el-radio :value="false">自定义权限</el-radio></el-radio-group>
            </el-form-item>
            <el-form-item label="数据范围"><el-select v-model="scope" aria-label="数据范围" :disabled="!canEdit || saving"><el-option v-for="item in scopeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
            <el-form-item v-if="policy.kind === 'user'" label="当前生效范围">{{ scopeLabel(policy.effective_data_scope ?? policy.data_scope) }}</el-form-item>
            <el-form-item v-if="policy.kind === 'user'" label="停用访问"><el-switch v-model="disabled" aria-label="停用访问" :disabled="!canEdit || saving" /></el-form-item>
          </el-form>
          <div class="permission-controls">
            <el-select v-model="module" aria-label="权限模块" @change="permissionPage = 1"><el-option v-for="item in modules" :key="item.key" :label="item.label" :value="item.key" /></el-select>
            <el-input v-model="search" aria-label="搜索接口权限" placeholder="搜索名称、方法或路径" clearable @input="permissionPage = 1" />
          </div>
          <p class="selection-count">{{ inherit ? '继承策略' : `已选择 ${selected.length} 项` }} · 当前匹配 {{ filteredPermissions.length }} 项{{ !inherit && !selected.length ? ' · 保存后禁止全部业务接口' : '' }}</p>
          <div class="permission-actions"><el-button size="small" :disabled="!canSelect" @click="selectPage(true)">选中本页</el-button><el-button size="small" :disabled="!canSelect" @click="selectPage(false)">取消本页</el-button></div>
          <el-checkbox-group v-model="selected" class="permission-list" aria-label="接口权限">
            <el-checkbox v-for="item in pagedPermissions" :key="item.code" :value="item.code" :disabled="!canSelect || !available.has(item.code)">
              <span>{{ item.label }}</span><code>{{ item.method }} {{ item.path }}</code>
            </el-checkbox>
          </el-checkbox-group>
          <el-pagination v-model:current-page="permissionPage" :page-size="40" :total="filteredPermissions.length" layout="prev, pager, next, total" />
        </template>
      </div>
      <template #footer><el-button :disabled="policyLoading || saving" @click="reloadPolicy">重新加载</el-button><el-button @click="policyVisible = false">关闭</el-button><el-button type="primary" :loading="saving" :disabled="!canEdit || policyLoading || conflict" @click="submitPolicy">保存权限</el-button></template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useStore } from 'vuex';
import { ElMessage, ElMessageBox } from 'element-plus';
import { getUserList, updateUserRole, resetUserPassword, deleteUser as apiDeleteUser } from '@/api/user';
import { getAccessCatalog, getAccessPolicy, saveAccessPolicy, getAccessAudit } from '@/api/access';
import { accessAudit, strategy as auditStrategy } from '@/utils/accessAudit.cjs';
const store = useStore(), tab = ref('users'), loading = ref(false), saving = ref(false), roles = ref([]), permissions = ref([]), users = ref([]), roleFilter = ref(''), audit = ref([]), auditPage = ref(1), auditTotal = ref(0);
const roleVisible = ref(false), currentUser = ref({}), newRole = ref(''), policyVisible = ref(false), policyLoading = ref(false), policy = ref(null), inherit = ref(true), selected = ref([]), scope = ref('existing'), disabled = ref(false), conflict = ref(false), module = ref(''), search = ref(''), permissionPage = ref(1);
let generation = 0, policyRequest = 0, userRequest = 0, auditRequest = 0, policyTarget;
const auditVisible = ref(false), auditDetail = ref(null), auditView = ref('changes');
const auditRows = computed(() => audit.value.map(row => ({ ...row, change: accessAudit(row.detail) })));
const permissionLabels = computed(() => new Map(permissions.value.map(item => [item.code, item])));
const auditGroups = computed(() => [{ label: '新增配置项', codes: auditDetail.value?.change.added || [] }, { label: '撤销配置项', codes: auditDetail.value?.change.removed || [] }]);
function openAudit(row) { if (!canReadAudit.value) return; auditDetail.value = row; auditView.value = 'changes'; auditVisible.value = true; }
const actor = ref(null), isSuper = computed(() => actor.value?.role === 'super_admin');
const identity = computed(() => JSON.stringify([store.state.user.accessToken, store.getters['user/username'], store.getters['user/permissions']]));
const authorized = computed(() => !!store.state.user.accessToken && (store.getters['user/permissions'] || []).some(role => ['admin', 'super_admin'].includes(role)));
const roleLabel = key => roles.value.find(role => role.key === key)?.label || key;
const manageable = key => !!roles.value.find(role => role.key === key)?.manageable;
const canCall = code => !store.getters['user/authorization'] || store.getters['user/authorization'].permission_codes.includes(code);
const canReadAudit = computed(() => authorized.value && canCall('GET /api/access/audit'));
const accountPaths = { role: 'updateRole', password: 'resetPassword', delete: 'delete' };
const accountAllowed = (row, operation) => authorized.value && canCall(`POST /api/user/${accountPaths[operation]}`) && (operation === 'password' || row.user_id !== actor.value?.user_id) && (isSuper.value || manageable(row.user_role));
const available = computed(() => new Set(policy.value?.available_permissions || []));
const modules = computed(() => [...new Map(permissions.value.map(item => [item.module, { key: item.module, label: item.module_label }])).values()]);
const scopeOptions = computed(() => roles.value.find(role => role.key === policy.value?.role || role.key === policy.value?.key)?.scope_options || [{ value: 'existing', label: '现有业务范围' }]);
const scopeLabel = value => scopeOptions.value.find(item => item.value === value)?.label || value;
const filteredPermissions = computed(() => { const keyword = search.value.trim().toLowerCase(); return permissions.value.filter(item => (!module.value || item.module === module.value) && (!keyword || `${item.label} ${item.method} ${item.path} ${item.code}`.toLowerCase().includes(keyword))); });
const pagedPermissions = computed(() => filteredPermissions.value.slice((permissionPage.value - 1) * 40, permissionPage.value * 40));
const canEdit = computed(() => policy.value?.editable && canCall('PUT /api/access/policies/{kind}/{key}'));
const canSelect = computed(() => canEdit.value && !inherit.value && !saving.value && !conflict.value);
function notify(error, fallback) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error?.response?.data?.detail || error?.msg || fallback); }
async function fetchUsers() { const serial = generation, request = ++userRequest; try { const res = await getUserList(roleFilter.value ? { role: roleFilter.value } : {}); if (serial === generation && request === userRequest && authorized.value) users.value = res.data || []; } catch (error) { if (serial === generation) notify(error, '用户查询失败'); } }
async function fetchAudit() { if (!canReadAudit.value) return; const serial = generation, request = ++auditRequest; try { const res = await getAccessAudit({ page: auditPage.value, page_size: 20 }); if (serial === generation && request === auditRequest && canReadAudit.value) { audit.value = res.data.list; auditTotal.value = res.data.total; } } catch (error) { if (serial === generation) notify(error, '审计查询失败'); } }
function changeTab(value) { if (value === 'audit') fetchAudit(); }
function openRole(row) { if (!accountAllowed(row, 'role')) return; currentUser.value = { ...row }; newRole.value = row.user_role; roleVisible.value = true; }
async function submitRole() { if (!accountAllowed(currentUser.value, 'role') || !isSuper.value && !manageable(newRole.value)) return; const serial = generation; saving.value = true; try { await updateUserRole({ user_id: currentUser.value.user_id, user_role: newRole.value }); if (serial !== generation) return; roleVisible.value = false; ElMessage.success('角色已保存'); await fetchUsers(); } catch (error) { notify(error, '角色保存失败'); } finally { saving.value = false; } }
async function resetPassword(row) { if (!accountAllowed(row, 'password')) return; const serial = generation; try { const { value } = await ElMessageBox.prompt(`设置 ${row.username} 的临时密码`, '重置密码', { inputType: 'password', inputPattern: /^.{6,128}$/, inputErrorMessage: '密码长度为 6 至 128 位', confirmButtonText: '重置密码', cancelButtonText: '取消' }); if (serial !== generation || !authorized.value) return; await resetUserPassword({ user_id: row.user_id, new_password: value }); ElMessage.success('密码已重置'); } catch (error) { notify(error, '密码重置失败'); } }
async function deleteUser(row) { if (!accountAllowed(row, 'delete')) return; const serial = generation; try { await ElMessageBox.confirm(`删除用户 ${row.username}？`, '删除用户', { type: 'warning' }); if (serial !== generation || !authorized.value) return; await apiDeleteUser({ user_id: row.user_id }); ElMessage.success('用户已删除'); await fetchUsers(); } catch (error) { notify(error, '删除失败'); } }
async function openPolicy(kind, key) {
  policyTarget = [kind, key];
  policyVisible.value = true; policyLoading.value = true; policy.value = null; conflict.value = false; selected.value = []; search.value = ''; permissionPage.value = 1;
  const serial = generation, request = ++policyRequest;
  try { const { data } = await getAccessPolicy(kind, key); if (serial !== generation || request !== policyRequest || !authorized.value) return; policy.value = data; inherit.value = data.allowed_permissions === null; selected.value = [...(data.allowed_permissions ?? data.effective_permissions)]; scope.value = data.data_scope; disabled.value = data.disabled; module.value = modules.value[0]?.key || ''; } catch (error) { if (serial === generation && request === policyRequest) notify(error, '权限查询失败'); } finally { if (request === policyRequest) policyLoading.value = false; }
}
function reloadPolicy() { if (policyTarget) openPolicy(...policyTarget); }
function selectPage(include) { const codes = pagedPermissions.value.filter(item => available.value.has(item.code)).map(item => item.code); selected.value = include ? [...new Set([...selected.value, ...codes])] : selected.value.filter(code => !codes.includes(code)); }
async function submitPolicy() {
  if (!canEdit.value || conflict.value || saving.value) return;
  const serial = generation, request = policyRequest, target = policy.value;
  saving.value = true;
  try { await saveAccessPolicy(target.kind, target.key, { expected_version: target.version, allowed_permissions: inherit.value ? null : selected.value.filter(code => available.value.has(code)), data_scope: scope.value, disabled: target.kind === 'user' && disabled.value }); if (serial === generation && request === policyRequest) { ElMessage.success('权限已保存'); await openPolicy(target.kind, target.key); } } catch (error) { if (serial === generation && request === policyRequest) { if (error?.response?.status === 409) conflict.value = true; else notify(error, '权限保存失败'); } } finally { saving.value = false; }
}
watch(canReadAudit, value => { if (!value) { auditRequest++; auditVisible.value = false; auditDetail.value = null; audit.value = []; auditTotal.value = 0; if (tab.value === 'audit') tab.value = 'users'; } });
watch(policyVisible, value => { if (!value) { policyRequest++; policyTarget = null; policy.value = null; policyLoading.value = false; } });
watch(identity, async () => { const serial = ++generation; policyRequest++; policyVisible.value = false; roleVisible.value = false; auditVisible.value = false; auditDetail.value = null; policy.value = null; actor.value = null; roles.value = []; permissions.value = []; users.value = []; audit.value = []; auditTotal.value = 0; if (!authorized.value) return; loading.value = true; try { const { data } = await getAccessCatalog(); if (serial !== generation || !authorized.value) return; actor.value = data.actor; roles.value = data.roles; permissions.value = data.permissions; await fetchUsers(); } catch (error) { if (serial === generation) notify(error, '权限目录加载失败'); } finally { if (serial === generation) loading.value = false; } }, { immediate: true });
</script>

<style scoped>
.permission-page :deep(.el-select) { width: 190px; }
.permission-controls { display: flex; gap: 12px; flex-wrap: wrap; }
.permission-controls .el-input { flex: 1; min-width: 180px; }
.permission-actions { display: flex; gap: 8px; margin: 12px 0; }
.permission-list { display: flex; flex-direction: column; align-items: stretch; min-height: 90px; }
.permission-list :deep(.el-checkbox) { height: auto; min-height: 48px; margin: 0; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.permission-list :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; }
.permission-list code { display: block; font-size: 12px; color: var(--el-text-color-secondary); }
.selection-count { color: var(--el-text-color-secondary); }
.audit-summary { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.5; max-height: 4.5em; }
.audit-content { height: 50vh; overflow: auto; }
.audit-raw { margin: 0; white-space: pre-wrap; font: inherit; overflow-wrap: anywhere; }
.audit-meta { color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.audit-permission { padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); overflow-wrap: anywhere; }
.audit-permission code { display: block; font-size: 12px; color: var(--el-text-color-secondary); }
.audit-content h4 { margin: 12px 0; }
.permission-page :deep(.el-pagination), :deep(.el-drawer .el-pagination) { margin-top: 16px; }
</style>
