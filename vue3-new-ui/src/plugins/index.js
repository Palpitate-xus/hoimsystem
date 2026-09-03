/* 公共引入,勿随意修改,修改时需经过确认 */
import "./support";
import "@/styles/vab.scss";
import "@/config/permission";
// 不再导入vab-icon
import VabPermissions from "layouts/Permissions";
import Vab from "@/utils/vab";
import { provideGlobalConfig } from "element-plus";
import zhCn from "element-plus/dist/locale/zh-cn.mjs";
import { faToElIcon } from "@/utils/vab";
import { h } from "vue";

// 创建全局VabIcon组件，用于替换之前的vab-icon
const VabIcon = {
  name: "VabIcon",
  props: {
    icon: {
      type: [String, Array],
      required: true,
    },
  },
  setup(props) {
    return () => {
      const iconComponent = faToElIcon(props.icon);
      return h("el-icon", {}, [h(iconComponent)]);
    };
  },
};

export default (app) => {
  // 按需组件仍共享中文语言包，避免 app.use(ElementPlus) 注册整个组件库。
  provideGlobalConfig({ locale: zhCn }, app, true);

  // 注册VabIcon组件，替代之前的vab-icon
  app.component("VabIcon", VabIcon);

  // 注册自定义插件
  app.use(Vab);
  app.use(VabPermissions);
};
