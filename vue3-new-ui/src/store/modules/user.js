/**

 * @description 登录、获取用户信息、退出登录、清除accessToken逻辑，不建议修改
 */

import { getUserInfo, login, logout } from "@/api/user";
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
});
const getters = {
  accessToken: (state) => state.accessToken,
  username: (state) => state.username,
  avatar: (state) => state.avatar,
  permissions: (state) => state.permissions,
};
const mutations = {
  setAccessToken(state, accessToken) {
    state.accessToken = accessToken;
    setAccessToken(accessToken);
  },
  setUsername(state, username) {
    state.username = username;
  },
  setAvatar(state, avatar) {
    state.avatar = avatar;
  },
  setPermissions(state, permissions) {
    state.permissions = permissions;
  },
};
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
      const { data } = await getUserInfo(state.accessToken);
      if (!data) {
        return false;
      }
      let { permissions, username, avatar } = data;
      if (permissions && username && Array.isArray(permissions)) {
        commit("setPermissions", permissions);
        commit("setUsername", username);
        commit("setAvatar", avatar);
        return permissions;
      } else {
        return false;
      }
    } catch (error) {
      return false;
    }
  },
  async logout({ dispatch }) {
    await logout(state.accessToken);
    await dispatch("resetAccessToken");
    await resetRouter();
    location.reload();
  },
  resetAccessToken({ commit }) {
    commit("setPermissions", []);
    commit("setAccessToken", "");
    removeAccessToken();
  },
};
export default { state, getters, mutations, actions };
