/**
 * @description 导出默认网路配置
 **/
const network = {
  // 接口地址指向 FastAPI 后端
  baseURL: process.env.NODE_ENV === "production" ? "/api" : "/api",
  //配后端数据的接收方式application/json;charset=UTF-8或者application/x-www-form-urlencoded;charset=UTF-8
  contentType: "application/json;charset=UTF-8",
  //消息框消失时间
  messageDuration: 3000,
  //最长请求时间
  requestTimeout: 15000,
  //操作正常code，支持String、Array、int多种类型
  successCode: [200],
  //登录失效code，改为999避免与后端业务错误500冲突
  invalidCode: 999,
  //无权限code
  noPermissionCode: 401,
};
module.exports = network;
