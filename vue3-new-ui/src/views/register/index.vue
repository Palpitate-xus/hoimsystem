<template>
  <div class="register-container">
    <div class="register-box">
      <div class="register-form-container">
        <div class="logo-container">
          <h2 class="welcome-text">患者注册</h2>
          <h3 class="system-title">医院门诊信息管理系统</h3>
        </div>

        <el-form
          ref="registerForm"
          class="register-form"
          :model="form"
          :rules="registerRules"
        >
          <el-form-item prop="username">
            <el-input
              v-model.trim="form.username"
              placeholder="请输入用户名"
              type="text"
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model.trim="form.password"
              placeholder="设置密码"
              type="password"
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="identity">
            <el-input
              v-model.trim="form.identity"
              placeholder="身份证号"
              type="text"
            >
              <template #prefix>
                <el-icon><Postcard /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="phone">
            <el-input
              v-model.trim="form.phone"
              placeholder="请输入手机号"
              maxlength="11"
              type="text"
            >
              <template #prefix>
                <el-icon><Cellphone /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="address">
            <el-input
              v-model.trim="form.address"
              placeholder="地址"
              type="text"
            >
              <template #prefix>
                <el-icon><Location /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item prop="sex">
            <el-select v-model="form.sex" placeholder="性别" style="width:100%" filterable>
              <el-option label="男" value="1" />
              <el-option label="女" value="0" />
            </el-select>
          </el-form-item>

          <el-form-item prop="birthday">
            <el-date-picker
              v-model="form.birthday"
              type="date"
              placeholder="生日"
              value-format="YYYY-MM-DD"
              style="width:100%"
            />
          </el-form-item>

          <el-button
            class="register-btn"
            type="primary"
            @click.prevent="handleRegister"
          >
            立即注册
          </el-button>

          <div class="login-link">
            <span>已有账号?</span>
            <router-link to="/login" class="back-to-login">
              返回登录
            </router-link>
          </div>
        </el-form>
      </div>

      <div class="register-image">
        <div class="overlay">
          <h2 class="slogan">健康 · 关爱 · 专业</h2>
          <p class="description">注册账号，享受便捷医疗服务</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, toRefs } from "vue";
import { isPassword, isPhone } from "@/utils/validate";
import { register } from "@/api/user";
import { ElMessage } from "element-plus";
import { User, Cellphone, Lock, Postcard, Location } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";

const state = reactive({
  form: {
    username: "",
    password: "",
    identity: "",
    phone: "",
    address: "",
    sex: "1",
    birthday: "",
  },
  registerRules: {
    username: [
      { required: true, trigger: "blur", message: "请输入用户名" },
    ],
    password: [
      { required: true, trigger: "blur", message: "请输入密码" },
      {
        validator: (rule, value, callback) => {
          if (!isPassword(value)) {
            callback(new Error("密码不能少于6位"));
          } else {
            callback();
          }
        },
        trigger: "blur",
      },
    ],
    identity: [
      { required: true, trigger: "blur", message: "请输入身份证号" },
    ],
    phone: [
      { required: true, trigger: "blur", message: "请输入手机号码" },
      {
        validator: (rule, value, callback) => {
          if (!isPhone(value)) {
            callback(new Error("请输入正确的手机号"));
          } else {
            callback();
          }
        },
        trigger: "blur",
      },
    ],
    address: [
      { required: true, trigger: "blur", message: "请输入地址" },
    ],
    sex: [
      { required: true, trigger: "blur", message: "请选择性别" },
    ],
    birthday: [
      { required: true, trigger: "blur", message: "请选择生日" },
    ],
  },
});

const registerForm = ref(null);
const router = useRouter();

const handleRegister = () => {
  registerForm.value?.validate(async (valid) => {
    if (valid) {
      try {
        const { msg } = await register(state.form);
        ElMessage.success(msg || "注册成功");
        setTimeout(() => {
          router.push("/login");
        }, 1500);
      } catch (error) {
        ElMessage.error(error.message || "注册失败");
      }
    }
  });
};

const { form, registerRules } = toRefs(state);
</script>

<style lang="scss" scoped>
.register-container {
  height: 100vh;
  width: 100vw;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
}

.register-box {
  width: 80%;
  max-width: 1000px;
  height: auto;
  min-height: 700px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  display: flex;
  background-color: #fff;
}

.register-form-container {
  width: 50%;
  padding: 40px 50px;
  display: flex;
  flex-direction: column;
}

.logo-container {
  margin-bottom: 20px;
  text-align: center;

  .welcome-text {
    font-size: 28px;
    color: #333;
    margin-bottom: 10px;
    font-weight: 600;
  }

  .system-title {
    font-size: 18px;
    color: #666;
    font-weight: 400;
  }
}

.register-form {
  flex: 1;

  .el-form-item {
    margin-bottom: 15px;
  }

  .el-input {
    height: 44px;

    :deep(.el-input__wrapper) {
      padding-left: 15px;
      box-shadow: 0 0 0 1px #dcdfe6 inset;
    }

    :deep(.el-input__prefix) {
      color: #909399;
      font-size: 18px;
    }
  }
}

.register-btn {
  width: 100%;
  height: 50px;
  border-radius: 25px;
  font-size: 16px;
  font-weight: 500;
  letter-spacing: 1px;
  background: linear-gradient(90deg, #409eff 0%, #007aff 100%);
  border: none;
  margin-top: 10px;

  &:hover {
    background: linear-gradient(90deg, #007aff 0%, #409eff 100%);
  }
}

.login-link {
  margin-top: 20px;
  text-align: center;
  font-size: 14px;
  color: #606266;

  .back-to-login {
    color: #409eff;
    text-decoration: none;
    margin-left: 5px;

    &:hover {
      text-decoration: underline;
    }
  }
}

.register-image {
  width: 50%;
  position: relative;
  background: url("~@/assets/login_images/background.jpg") center center
    no-repeat;
  background-size: cover;

  .overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 40px;

    .slogan {
      color: #fff;
      font-size: 32px;
      font-weight: 600;
      margin-bottom: 20px;
      text-align: center;
    }

    .description {
      color: rgba(255, 255, 255, 0.9);
      font-size: 16px;
      text-align: center;
    }
  }
}

@media screen and (max-width: 992px) {
  .register-box {
    width: 100%;
    max-width: 100%;
    flex-direction: column;
    height: auto;
    max-height: 90vh;
    overflow-y: auto;
  }

  .register-form-container,
  .register-image {
    width: 100%;
  }

  .register-image {
    height: 200px;
    order: -1;
  }
}

@media screen and (max-width: 576px) {
  .register-container {
    padding: 0;
    height: 100%;
    background: #fff;
  }

  .register-box {
    width: 100%;
    max-width: 100%;
    height: 100%;
    border-radius: 0;
    box-shadow: none;
  }

  .register-form-container {
    padding: 20px;
    width: 100%;
    box-sizing: border-box;
  }

  .register-form {
    .el-form-item {
      margin-bottom: 12px;
      width: 100%;
    }

    :deep(.el-input) {
      width: 100%;

      .el-input__wrapper {
        width: 100%;
        box-sizing: border-box;
      }
    }
  }

  .logo-container {
    margin-bottom: 15px;

    .welcome-text {
      font-size: 24px;
    }

    .system-title {
      font-size: 16px;
    }
  }

  .register-btn {
    height: 45px;
    font-size: 15px;
  }
}
</style>
