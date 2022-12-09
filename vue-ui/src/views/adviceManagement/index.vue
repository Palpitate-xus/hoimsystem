<template>
  <div>
    <el-form ref="form" :model="form" label-width="140px">
      <el-form-item label="病人选择">
        <el-select v-model="form.department" placeholder="请选择病人">
          <el-option
            v-for="item in departmentList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医嘱内容">
        <el-input
          v-model="form.content"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 8 }"
        ></el-input>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">查找</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  export default {
    name: 'Index',
  }
</script>
