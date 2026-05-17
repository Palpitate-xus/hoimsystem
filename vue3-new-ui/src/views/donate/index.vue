<template>
  <div class="donate-container">
    <div class="donate-header">
      <h1>系统更新日志</h1>
      <p>持续优化医疗服务体验</p>
      <p>为智慧医疗建设贡献力量 💖</p>
    </div>

    <div class="donate-content">
      <div class="payment-method">
        <h3>系统版本信息</h3>
        <div style="text-align: left; padding: 20px;">
          <p><strong>当前版本：</strong>v1.0.0</p>
          <p><strong>系统名称：</strong>医院门诊信息管理系统</p>
          <p><strong>技术栈：</strong>Vue 3 + Element Plus + FastAPI</p>
          <p><strong>更新日期：</strong>2025年</p>
          <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #e8e8e8;">
            <p style="color: #666; font-size: 13px;">本系统专注于提供高效、便捷、安全的医疗服务</p>
          </div>
        </div>
      </div>
      <div></div>
    </div>
  </div>
</template>

<script>
  export default {
    name: 'DonatePage',
    data() {
      return {
        // 可以添加捐赠相关的状态数据
      }
    },
    methods: {
      // 可以添加捐赠相关的方法
    },
  }
</script>

<style scoped>
  .donate-container {
    margin: 0 auto;
    padding: 40px 20px;
  }

  .donate-header {
    text-align: center;
    margin-bottom: 40px;
  }

  .donate-header h1 {
    color: #1890ff;
    font-size: 32px;
    margin-bottom: 16px;
  }

  .donate-header p {
    color: #666;
    font-size: 18px;
  }

  .donate-content {
    display: flex;
    justify-content: space-around;
    flex-wrap: wrap;
    gap: 40px;
    margin-bottom: 40px;
  }

  .payment-method {
    background: #fff;
    border-radius: 12px;
    padding: 30px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    text-align: center;
    transition: transform 0.3s ease, box-shadow 0.3s ease;
    flex: 1;
    min-width: 300px;
  }

  .payment-method h3 {
    color: #333;
    margin-bottom: 20px;
    font-size: 20px;
  }

  .qr-code-container {
    margin-bottom: 20px;
  }

  .qr-code {
    max-width: 200px;
    height: auto;
    border-radius: 8px;
    border: 1px solid #e8e8e8;
  }

  .instruction {
    color: #666;
    font-size: 14px;
  }

  @media (max-width: 768px) {
    .donate-content {
      flex-direction: column;
      align-items: center;
    }

    .payment-method {
      width: 100%;
      max-width: 400px;
    }
  }
</style>
