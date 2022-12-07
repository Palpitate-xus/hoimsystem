<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="通知标题">
        <el-input
          v-model="form.title"
          maxlength="12"
          show-word-limit
        ></el-input>
      </el-form-item>
      <el-form-item label="通知内容">
        <el-input
          v-model="form.content"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 8 }"
        ></el-input>
      </el-form-item>
      <el-form-item label="是否紧急">
        <el-switch
          v-model="form.isemergency"
          active-value="1"
          inactive-value="0"
        ></el-switch>
      </el-form-item>
      <el-form-item label="过期时间">
        <el-date-picker
          v-model="form.expiredtime"
          type="datetime"
          placeholder="选择日期时间"
        ></el-date-picker>
      </el-form-item>
      <el-form-item label="发送对象">
        <el-checkbox-group v-model="form.towho">
          <el-checkbox label="科室主任" name="type"></el-checkbox>
          <el-checkbox label="医生" name="type"></el-checkbox>
          <el-checkbox label="病人" name="type"></el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">发送</el-button>
        <el-button @click="cancel">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  import { noticeRegister } from '../../api/notice'
  export default {
    name: 'NoticeRegister',
    data() {
      return {
        form: {
          towho: [],
          isemergency: 0,
        },
      }
    },
    methods: {
      async onSubmit() {
        console.log('submit!')
        await noticeRegister(this.form)
        this.$baseMessage('发送成功', 'success')
        this.cancel()
      },
      cancel() {
        this.form = {
          towho: [],
          isemergency: 0,
        }
      },
    },
  }
</script>
