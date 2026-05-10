<template>
  <div class="app-container">
    <vab-page-header title="智能导诊" description="输入症状描述，获取智能科室推荐" />
    <el-card>
      <div style="max-width: 700px; margin: 0 auto;">
        <h3 style="text-align: center; margin-bottom: 20px; color: #303133;">
          <el-icon><FirstAidKit /></el-icon> 请描述您的症状
        </h3>
        <el-input
          v-model="symptomText"
          type="textarea"
          :rows="4"
          placeholder="例如：我最近经常头痛、头晕，有时还会恶心..."
          maxlength="200"
          show-word-limit
        />
        <div style="margin-top: 15px; text-align: center;">
          <el-button type="primary" size="large" @click="submitTriage" :loading="loading">
            <el-icon><Search /></el-icon> 智能导诊
          </el-button>
          <el-button size="large" @click="symptomText = ''">清空</el-button>
        </div>

        <!-- 推荐科室 -->
        <div v-if="suggestions.length > 0" style="margin-top: 30px;">
          <h4 style="color: #303133; margin-bottom: 15px;">推荐科室</h4>
          <el-row :gutter="15">
            <el-col v-for="(item, index) in suggestions" :key="index" :span="24" style="margin-bottom: 15px;">
              <el-card shadow="hover" :body-style="{ padding: '15px' }">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <div style="font-size: 18px; font-weight: bold; color: #303133;">
                      {{ item.department }}
                      <el-tag v-if="index === 0" type="danger" size="small" style="margin-left: 8px;">最推荐</el-tag>
                      <el-tag v-else-if="index === 1" type="warning" size="small" style="margin-left: 8px;">次推荐</el-tag>
                    </div>
                    <div style="margin-top: 8px; color: #606266; font-size: 14px;">
                      <span v-if="item.matched_keywords && item.matched_keywords.length > 0">
                        匹配症状:
                        <el-tag v-for="kw in item.matched_keywords" :key="kw" size="small" type="success" style="margin-right: 5px;">{{ kw }}</el-tag>
                      </span>
                    </div>
                    <div v-if="item.location" style="margin-top: 5px; color: #909399; font-size: 13px;">
                      位置: {{ item.location }}
                      <span v-if="item.phone"> | 电话: {{ item.phone }}</span>
                    </div>
                  </div>
                  <el-button
                    v-if="item.department_id"
                    type="primary"
                    @click="goAppointment(item.department_id)"
                  >
                    去挂号
                  </el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>

        <!-- 症状关键词提示 -->
        <div v-if="keywords.length > 0" style="margin-top: 30px;">
          <h4 style="color: #606266; margin-bottom: 10px; font-size: 14px;">常见症状关键词（点击填入）</h4>
          <div>
            <el-tag
              v-for="kw in displayedKeywords"
              :key="kw"
              style="margin: 3px; cursor: pointer;"
              @click="appendKeyword(kw)"
            >
              {{ kw }}
            </el-tag>
            <el-link v-if="keywords.length > 30" type="primary" @click="showAllKeywords = !showAllKeywords" style="margin-left: 10px;">
              {{ showAllKeywords ? '收起' : '更多' }}
            </el-link>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { triageSuggest, getTriageKeywords } from "@/api/triage";

const router = useRouter();
const symptomText = ref("");
const loading = ref(false);
const suggestions = ref([]);
const keywords = ref([]);
const showAllKeywords = ref(false);

const displayedKeywords = computed(() => {
  if (showAllKeywords.value) return keywords.value;
  return keywords.value.slice(0, 30);
});

const submitTriage = async () => {
  if (!symptomText.value.trim()) {
    ElMessage.warning("请输入症状描述");
    return;
  }
  loading.value = true;
  try {
    const res = await triageSuggest({ symptom: symptomText.value.trim() });
    if (res.code === 200) {
      suggestions.value = res.data.suggestions || [];
      if (suggestions.value.length === 0) {
        ElMessage.info("未找到匹配科室，建议前往综合门诊或急诊科");
      }
    } else {
      ElMessage.error(res.msg || "导诊失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "导诊失败");
  }
  loading.value = false;
};

const appendKeyword = (kw) => {
  if (symptomText.value) {
    symptomText.value += "，" + kw;
  } else {
    symptomText.value = kw;
  }
};

const goAppointment = (deptId) => {
  router.push({ path: "/patient/appointment", query: { department_id: deptId } });
};

const loadKeywords = async () => {
  try {
    const res = await getTriageKeywords();
    if (res.code === 200) {
      keywords.value = res.data || [];
    }
  } catch (e) {
    // ignore
  }
};

onMounted(loadKeywords);
</script>
