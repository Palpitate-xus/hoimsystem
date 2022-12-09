<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="选择病人">
        <el-select v-model="form.patient" placeholder="请选择病人">
          <el-option
            v-for="item in patientList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="选择检查类型">
        <el-row :gutter="8">
          <el-col :span="4">
            <el-select v-model="ins_choose" placeholder="请选择检查类型">
              <el-option
                v-for="item in phaList"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              ></el-option>
            </el-select>
          </el-col>
          <el-col :span="4">
            <el-input
              v-model="ins_body"
              placeholder="请输入检查部位"
            ></el-input>
          </el-col>
          <el-col :span="8">
            <el-button @click="addPha">加入</el-button>
          </el-col>
        </el-row>
      </el-form-item>
    </el-form>
    <el-table
      v-loading="listLoading"
      :data="pha_submit"
      :element-loading-text="elementLoadingText"
    >
      <el-table-column
        show-overflow-tooltip
        prop="id"
        label="id"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="name"
        label="检查名称"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="number"
        label="检查部位"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button
      style="margin-top: 10px; text-align: center"
      type="primary"
      @click="onSubmit"
    >
      提交
    </el-button>
    <el-button @click="cancel">取消</el-button>
    <bultrasound ref="bus"></bultrasound>
  </div>
</template>

<script>

  import { prescriptionRegister } from '../../api/prescriptionManagement'
  import Bultrasound from './InspectionTemplates/Bultrasound.vue'
  export default {
    name: 'InspectionDoctor',
    components: {
      Bultrasound,
    },
    data() {
      return {
        form: {
          patient: 1,
          phas: [],
        },
        patientList: [],
        phaList: [],
        pha_submit: [],
        pha_choose: null,
        pha_number: null,
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const patient_data = await getPatientList()
        this.patientList = patient_data.data
        const pha_data = await getPharmaceuticalList()
        this.phaList = pha_data.data
      },
      async onSubmit() {
        console.log('submit!')
        this.form.phas = this.pha_submit
        await prescriptionRegister(this.form)
        this.$baseMessage('提交成功', 'success')
        this.cancel()
      },
      async addPha() {
        let array = this.pha_submit
        let flag = 1
        for (let index = 0; index < array.length; index++) {
          if (array[index].id === this.pha_choose) {
            this.$baseMessage('已有重复项目', 'error')
            flag = 0
          }
        }
        let pha_name = ''
        array = this.phaList
        for (let index = 0; index < array.length; index++) {
          if (array[index].id === this.pha_choose) {
            pha_name = array[index].name
            console.log(pha_name)
          }
        }
        const { data } = await getPharmaceuticalStock({ id: this.pha_choose })
        if (data.stock < this.pha_number) {
          flag = 0
          this.$baseMessage('库存不足，当前库存：' + data.stock, 'error')
        }
        if (flag) {
          this.pha_submit.push({
            id: this.pha_choose,
            name: pha_name,
            number: this.pha_number,
          })
        }
      },
      handleDelete(row) {
        this.pha_submit.map((val, i) => {
          if (val.id === row.id) {
            this.pha_submit.splice(i, 1)
            console.log(this.pha_submit)
          }
        })
      },
      cancel() {
        this.form = {
          patient: 1,
        }
      },
    },
  }
</script>
