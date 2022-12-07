<template>
  <div>
    <el-form ref="form" :model="form" label-width="140px">
      <el-form-item label="科室选择">
        <el-select v-model="form.department" placeholder="请选择科室">
          <el-option
            v-for="item in departmentList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医生姓名">
        <el-select v-model="form.doctor" placeholder="请选择医生">
          <el-option
            v-for="item in doctorList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="就诊时间段">
        <el-select v-model="form.time" placeholder="请选择就诊时间段">
          <el-option
            v-for="item in timeSlotList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
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
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="时间段"
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
          <el-button type="text" @click="handleEdit(row)">挂号</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import { getDepartmentList } from '../../api/departmentManagement'
  import { getDoctorList } from '../../api/doctorManagement'
  export default {
    name: 'RegistrationManagement',
    data() {
      return {
        form: {},
        departmentList: [],
        doctorList: [],
        timeSlotList: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const data_department = await getDepartmentList()
        const data_doctor = await getDoctorList()
        this.departmentList = data_department.data
        this.doctorList = data_doctor.data
      },
      onSubmit() {
        console.log('submit!')
      },
    },
  }
</script>
