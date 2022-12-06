<template>
  <div>
    <el-form ref="form" :model="form" label-width="140px">
      <el-form-item label="科室选择">
        <el-select v-model="form.region" placeholder="请选择科室">
          <el-option label="上午" value="shanghai"></el-option>
          <el-option label="下午" value="beijing"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医生姓名">
        <el-select v-model="form.region" placeholder="请选择医生">
          <el-option label="上午" value="shanghai"></el-option>
          <el-option label="下午" value="beijing"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="预约日期">
        <el-date-picker
          v-model="form.date"
          align="right"
          type="date"
          placeholder="选择日期"
          :picker-options="pickerOptions"
        ></el-date-picker>
      </el-form-item>
      <el-form-item label="就诊时间段">
        <el-select v-model="form.region" placeholder="请选择就诊时间段">
          <el-option label="上午" value="shanghai"></el-option>
          <el-option label="下午" value="beijing"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="是否专家号">
        <el-switch v-model="form.delivery"></el-switch>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">查找</el-button>
      </el-form-item>
    </el-form>
    <el-table
      v-loading="listLoading"
      :data="list"
      :element-loading-text="elementLoadingText"
    >
      <el-table-column
        show-overflow-tooltip
        prop="id"
        label="id"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="日期"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="时间段"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="类别"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="email"
        label="剩余号源数量"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleEdit(row)">预约</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  export default {
    name: 'Index',
    data() {
      return {
        form: {
          name: '',
          region: '',
          date1: '',
          date2: '',
          delivery: false,
          type: [],
          resource: '',
          desc: '',
        },
        pickerOptions: {
          disabledDate(time) {
            return time.getTime() > Date.now() + 3600 * 1000 * 24 * 7
          },
        },
      }
    },
    methods: {
      onSubmit() {
        console.log('submit!')
      },
    },
  }
</script>
