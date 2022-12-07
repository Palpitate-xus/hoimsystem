<template>
  <div class="magnifier-container">
    <el-row :gutter="20">
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card class="box-card">
          <div slot="header" class="clearfix">
            <span>卡片名称</span>
            <el-button style="float: right; padding: 3px 0" type="text">
              操作按钮
            </el-button>
          </div>
          <div v-for="o in 4" :key="o" class="text item">
            {{ '列表内容 ' + o }}
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-row>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>当前挂号情况</el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>当前预约情况</el-card>
      </el-col>
    </el-row>
    <el-row>
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card>当前医嘱</el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
  import { getNoticeList } from '../../api/notice'
  import { getAppointmentList } from '../../api/appointmentManagement'
  import { getRegistrationList } from '../../api/registrationManagement'
  export default {
    name: 'Index',
    data() {
      return {
        notices: [],
        appointments: [],
        registrations: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      fetchData() {
        this.notices = getNoticeList()
        this.appointments = getAppointmentList()
        this.registrations = getRegistrationList()
      },
    },
  }
</script>
