<template>
  <el-card class="version-information" shadow="hover">
    <template #header>
      <vab-icon icon="information-line" />
    </template>
    <el-scrollbar>
      <table class="table">
        <tbody>
          <tr>
            <td>vue</td>
            <td>{{ dependencies["vue"] }}</td>
            <td>rspack</td>
            <td>{{ devDependencies["@vue/cli-service"] }}</td>
          </tr>
          <tr>
            <td>vuex</td>
            <td>{{ dependencies["vuex"] }}</td>
            <td>vue-router</td>
            <td>{{ dependencies["vue-router"] }}</td>
          </tr>
          <tr>
            <td>element-plus</td>
            <td>{{ dependencies["element-plus"] }}</td>
            <td>axios</td>
            <td>{{ dependencies["axios"] }}</td>
          </tr>
          <tr>
            <td>系统版本</td>
            <td colspan="3">
              <el-tag type="success">v1.0.0</el-tag>
              <span style="margin-left: 10px; color: #666;">医院门诊信息管理系统</span>
            </td>
          </tr>
        </tbody>
      </table>
    </el-scrollbar>
  </el-card>
</template>

<script>
// 安全注意：不要把整个 package.json 打进公开产物（暴露完整技术栈指纹）。
// 仅提取展示所需的少量版本号。
import pkg from "../../../../package.json";

const dependencyVersions = {};
for (const name of ["vue", "vuex", "vue-router", "element-plus", "axios"]) {
  if (pkg.dependencies && pkg.dependencies[name]) dependencyVersions[name] = pkg.dependencies[name];
}

export default {
  data() {
    return {
      updateTime: process.env.VUE_APP_UPDATE_TIME,
      dependencies: dependencyVersions,
      devDependencies: { "@vue/cli-service": "-" },
    };
  },
};
</script>

<style lang="scss" scoped>
.version-information {
  .table {
    width: 100%;
    color: #666;
    border-collapse: collapse;
    background-color: #fff;

    td {
      position: relative;
      padding: 9px 15px;
      overflow: hidden;
      font-size: 14px;
      line-height: 20px;
      text-overflow: ellipsis;
      white-space: nowrap;
      border: 1px solid #e6e6e6;

      &:nth-child(odd) {
        width: 20%;
        text-align: right;
        background-color: #f7f7f7;
      }
    }
  }
}
</style>
