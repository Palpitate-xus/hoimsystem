/**

 * @description 路由拦截状态管理，目前两种模式：all模式与intelligence模式
 */
import { asyncRoutes, constantRoutes } from '@/router'
import { getRouterList } from '@/api/router'
import { convertRouter, filterAsyncRoutes } from '@/utils/handleRoutes'

const state = () => ({
  routes: [],
  partialRoutes: [],
})
const getters = {
  routes: (state) => state.routes,
  partialRoutes: (state) => state.partialRoutes,
}
const mutations = {
  setRoutes(state, routes) {
    state.routes = constantRoutes.concat(routes)
  },
  setAllRoutes(state, routes) {
    state.routes = constantRoutes.concat(routes)
  },
}
const actions = {
  /**
  
   * @description intelligence模式设置路由
   * @param {*} { commit }
   * @param {*} permissions
   * @returns
   */
  async setRoutes({ commit, rootGetters }, permissions) {
    //根据permissions做路由筛选
    const registeredRoutes = filterAsyncRoutes(asyncRoutes, permissions)
    const denied = rootGetters['user/authorization']?.denied_route_names || []
    const accessedRoutes = filterAsyncRoutes(registeredRoutes, permissions, denied)
    commit('setRoutes', accessedRoutes)
    return registeredRoutes
  },
  /**
  
   * @description all模式设置路由
   * @param {*} { commit }
   * @returns
   */
  async setAllRoutes({ commit, rootGetters }) {
    try {
      let { data } = await getRouterList()
      if (!data || !Array.isArray(data)) {
        console.error('后端返回的路由数据格式不正确', data)
        data = []
      }

      const accessedRoutes = convertRouter(data)
      commit('setAllRoutes', filterAsyncRoutes(accessedRoutes, rootGetters['user/permissions'], rootGetters['user/authorization']?.denied_route_names || []))
      return accessedRoutes
    } catch (error) {
      console.error('获取路由列表失败', error)
      commit('setAllRoutes', [])
      return []
    }
  },
}
export default { state, getters, mutations, actions }
