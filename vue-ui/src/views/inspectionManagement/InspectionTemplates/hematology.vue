<template>
  <div>
    <el-dialog
      title="血常规检查结果查看"
      :visible.sync="dialogVisible"
      width="60%"
      :before-close="handleClose"
    >
      <el-descriptions title="检查医生：wms">
        <el-descriptions-item label="血红蛋白">
          {{ form.hemoglobin }}
        </el-descriptions-item>
        <el-descriptions-item label="血小板">
          {{ form.platelet }}
        </el-descriptions-item>
        <el-descriptions-item label="白细胞">
          {{ form.leucocyte }}
        </el-descriptions-item>
        <el-descriptions-item label="红细胞">
          {{ form.hematid }}
        </el-descriptions-item>
        <el-descriptions-item label="中性粒细胞">
          {{ form.neutrohpils }}
        </el-descriptions-item>
        <el-descriptions-item label="单核细胞">
          {{ form.monocyte }}
        </el-descriptions-item>
        <el-descriptions-item label="淋巴细胞">
          {{ form.lym }}
        </el-descriptions-item>
        <el-descriptions-item label="嗜酸性粒细胞">
          {{ form.eos }}
        </el-descriptions-item>
        <el-descriptions-item label="嗜碱性粒细胞">
          {{ form.baso }}
        </el-descriptions-item>
        <el-descriptions-item label="血糖">
          {{ form.glu }}
        </el-descriptions-item>
        <el-descriptions-item label="血清谷丙转氨酶">
          {{ form.alt }}
        </el-descriptions-item>
        <el-descriptions-item label="血清谷草转氨酶">
          {{ form.ast }}
        </el-descriptions-item>
        <el-descriptions-item label="血清总胆红素">
          {{ form.tbil }}
        </el-descriptions-item>
        <el-descriptions-item label="血清直接胆红素">
          {{ form.dbil }}
        </el-descriptions-item>
        <el-descriptions-item label="血清肌酐">
          {{ form.crea }}
        </el-descriptions-item>
        <el-descriptions-item label="血清尿酸">
          {{ form.ua }}
        </el-descriptions-item>
        <el-descriptions-item label="血清总胆固醇">
          {{ form.cho }}
        </el-descriptions-item>
        <el-descriptions-item label="血清甘油三酯">
          {{ form.tg }}
        </el-descriptions-item>
        <el-descriptions-item label="血清高密度脂蛋白">
          {{ form.hdl_c }}
        </el-descriptions-item>
        <el-descriptions-item label="血清低密度脂蛋白">
          {{ form.ldl_c }}
        </el-descriptions-item>
      </el-descriptions>
      <span slot="footer" class="dialog-footer">
        <el-button @click="dialogVisible = false">取 消</el-button>
        <el-button type="primary" @click="dialogVisible = false">
          确 定
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
  export default {
    name: 'Hematology',
    data() {
      return {
        dialogVisible: false,
        form: {
          hemoglobin: '160 g/L',
          platelet: '350x10e9 /L',
          leucocyte: '8.0x10e9 /L',
          hematid: '5.0x10e12 /L',
          neutrohpils: '60%',
          monocyte: '8%',
          lym: '35%',
          eos: '5%',
          baso: '1%',
          glu: '5.0 mmol/L',
          alt: '35 U/L',
          ast: '25 U/L',
          tbil: '12.0 μmol/L',
          dbil: '3.6 μmol/L',
          crea: '72 μmol/L',
          ua: '360 μmol/L',
          cho: '4.5 mmol/L',
          tg: '2.0 mmol/L',
          hdl_c: '1.2 mmol/L',
          ldl_c: '3.6 mmol/L',
        },
      }
    },
  }
</script>
