import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import store from "@/store"; // 导入Vuex store
import plugins from "./plugins";
// 导入布局组件注册函数
import { registerLayoutComponents } from "@/layouts/export";
// 导入事件总线
import eventBus from "@/utils/eventBus";
// 导入配置
import { title } from "@/config";
// 导入mock
import { mockXHR } from "@/utils/static";

/**
 * @description 医院门诊信息管理系统前端入口
 */

// 创建应用实例
const app = createApp(App);

// 使用Vuex
app.use(store);

app.use(router);

// 初始化所有插件
plugins(app);

// 注册所有布局组件
registerLayoutComponents(app);

// 添加事件总线到全局属性
app.config.globalProperties.$eventBus = eventBus;

// 添加全局标题
app.config.globalProperties.$baseTitle = title;

// 使全局属性在window上也可用
window.$eventBus = eventBus;
window.$baseTitle = title;

// 抑制 ResizeObserver loop 运行时警告（Element Plus 组件常见，不影响功能）
const resizeObserverLoopErr = "ResizeObserver loop completed with undelivered notifications";
const isResizeObserverErr = (msg) =>
  typeof msg === "string" && msg.includes("ResizeObserver loop");

// Vue 全局错误处理
app.config.errorHandler = (err) => {
  if (isResizeObserverErr(err?.message)) return;
  console.error(err);
};

// window 错误事件拦截
window.addEventListener("error", (e) => {
  if (isResizeObserverErr(e.message)) {
    e.stopImmediatePropagation();
    e.preventDefault();
  }
});

// unhandledrejection 拦截
window.addEventListener("unhandledrejection", (e) => {
  if (isResizeObserverErr(e.reason?.message)) {
    e.stopImmediatePropagation();
    e.preventDefault();
  }
});

// console.error 过滤，阻止 rspack overlay 弹窗
const originalConsoleError = console.error;
console.error = function (...args) {
  if (args[0] && isResizeObserverErr(args[0]?.message ?? args[0])) return;
  originalConsoleError.apply(console, args);
};

// 检测环境变量，生产环境启用mock
if (process.env.NODE_ENV === "production") {
  // 生产环境初始化mock
  mockXHR();
  console.log("生产环境已启用Mock拦截，所有接口请求将被Mock拦截");
}
// 挂载应用
app.mount("#hoim");
