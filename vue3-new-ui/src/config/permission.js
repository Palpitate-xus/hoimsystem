import router from '@/router';
import store from '@/store';
import eventBus from '@/utils/eventBus';
import VabProgress from 'nprogress';
import 'nprogress/nprogress.css';
import getPageTitle from '@/utils/pageTitle';
import { authentication, loginInterception, progressBar, recordRoute, routesWhiteList } from '@/config';

VabProgress.configure({ easing: 'ease', speed: 500, trickleSpeed: 200, showSpinner: false });
const denied = route => {
  const names = store.getters['user/authorization']?.denied_route_names || [];
  return [route, ...(route.matched || [])].some(item => item.name && names.includes(item.name));
};
async function updateRoutes() {
  const routes = authentication === 'all'
    ? await store.dispatch('routes/setAllRoutes')
    : await store.dispatch('routes/setRoutes', store.getters['user/permissions']);
  (routes || []).forEach(route => router.addRoute(route));
}
let refreshing;
function refreshAccess(event) {
  if (event?.token && event.token !== store.getters['user/accessToken']) return;
  if (!store.getters['user/accessToken'] || !store.getters['user/authorization'] || refreshing) return refreshing;
  const token = store.getters['user/accessToken'];
  refreshing = store.dispatch('user/refreshAuthorization').then(async snapshot => {
    if (!snapshot || token !== store.getters['user/accessToken']) return;
    await updateRoutes();
    if (denied(router.currentRoute.value)) await router.replace('/401');
  }).catch(() => {}).finally(() => { refreshing = null; });
  return refreshing;
}
eventBus.on('access-denied', refreshAccess);
eventBus.on('clinical-event', event => { if (event.type === 'access.policy_changed') refreshAccess(); });

router.beforeEach(async (to, from, next) => {
  if (progressBar) VabProgress.start();
  document.title = getPageTitle(to.meta.title);
  const hasToken = !loginInterception || store.getters['user/accessToken'];
  if (!hasToken) {
    next(routesWhiteList.includes(to.path) ? undefined : recordRoute ? { path: '/login', query: { redirect: to.fullPath } } : '/login');
  } else if (to.path === '/login') {
    next('/');
  } else if (store.getters['user/permissions']?.length) {
    next(denied(to) ? '/401' : undefined);
  } else {
    try {
      const permissions = !loginInterception
        ? (await store.dispatch('user/setPermissions', ['admin']), ['admin'])
        : await store.dispatch('user/getUserInfo');
      if (!permissions) throw new Error('获取用户权限失败');
      await updateRoutes();
      const resolved = router.resolve(to.fullPath);
      next(denied(resolved) ? '/401' : { ...to, replace: true });
    } catch {
      await store.dispatch('user/resetAccessToken');
      next({ path: '/login', query: { redirect: to.fullPath } });
    }
  }
  if (progressBar) VabProgress.done();
});
router.afterEach(() => { if (progressBar) VabProgress.done(); });
