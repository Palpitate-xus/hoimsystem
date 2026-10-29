/**

 * @description 登录、获取用户信息、退出登录、清除accessToken逻辑，不建议修改
 */

import { getUserInfo, login, logout } from "@/api/user";
import { getMyAccess } from "@/api/access";
import {
  getAccessToken,
  removeAccessToken,
  setAccessToken,
} from "@/utils/accessToken";
import { resetRouter } from "@/router";
import { tokenName } from "@/config";
import { ElMessage } from "element-plus";

const state = () => ({
  accessToken: getAccessToken(),
  username: "",
  avatar: "",
  permissions: [],
  authorization: null,
});
const getters = {
  accessToken: (state) => state.accessToken,
  username: (state) => state.username,
  avatar: (state) => state.avatar,
  permissions: (state) => state.permissions,
  authorization: (state) => state.authorization,
};
const mutations = {
  setAuthorization(state, value) {
    if (!validAuthorization(value)) throw new Error("权限数据格式错误");
    state.authorization = value ?? null;
  },
  setAccessToken(state, accessToken) {
    if (state.accessToken !== accessToken) state.authorization = null;
    state.accessToken = accessToken;
    setAccessToken(accessToken);
  },
  setUsername(state, username) {
    if (state.username !== username) state.authorization = null;
    state.username = username;
  },
  setAvatar(state, avatar) {
    state.avatar = avatar;
  },
  setPermissions(state, permissions) {
    if (JSON.stringify(state.permissions) !== JSON.stringify(permissions)) state.authorization = null;
    state.permissions = permissions;
  },
};
function validAuthorization(value) {
  return value == null || typeof value.version === 'string' && ['existing', 'assigned'].includes(value.data_scope) &&
    ['permission_codes', 'denied_route_names'].every(key => Array.isArray(value[key]) && value[key].every(item => typeof item === 'string'));
}
const actions = {
  setPermissions({ commit }, permissions) {
    commit("setPermissions", permissions);
  },
  async login({ commit }, userInfo) {
    const { data } = await login(userInfo);
    const accessToken = data[tokenName];
    if (accessToken) {
      commit("setAccessToken", accessToken);
    } else {
      ElMessage.error("登录未完成，请重试。");
    }
  },
  async getUserInfo({ commit, state }) {
    try {
      const token = state.accessToken;
      const { data } = await getUserInfo(token);
      if (state.accessToken !== token || !data) {
        return false;
      }
      let { permissions, username, avatar } = data;
      if (permissions && username && Array.isArray(permissions)) {
        commit("setPermissions", permissions);
        commit("setUsername", username);
        commit("setAvatar", avatar);
        commit("setAuthorization", data.authorization);
        return permissions;
      } else {
        return false;
      }
    } catch (error) {
      return false;
    }
  },
  async refreshAuthorization({ commit, state }) {
    const token = state.accessToken, username = state.username;
    if (!token) return null;
    const { data } = await getMyAccess();
    if (state.accessToken !== token || state.username !== username) return null;
    commit("setAuthorization", data);
    return state.authorization;
  },
  async logout({ dispatch }) {
    await logout();
    await dispatch("resetAccessToken");
    await resetRouter();
    location.reload();
  },
  resetAccessToken({ commit }) {
    commit("setPermissions", []);
    commit("setAuthorization", null);
    commit("setUsername", "");
    commit("setAvatar", "");
    commit("setAccessToken", "");
    removeAccessToken();
  },
};
export default { state, getters, mutations, actions };
