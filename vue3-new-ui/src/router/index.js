import { createRouter, createWebHashHistory } from "vue-router";
import Layout from "@/layouts/index.vue";
import EmptyLayout from "@/layouts/EmptyLayout.vue";
import { publicPath } from "@/config";

export const constantRoutes = [
  {
    path: "/login",
    component: () => import("@/views/login/index.vue"),
    hidden: true,
  },
  {
    path: "/register",
    component: () => import("@/views/register/index.vue"),
    hidden: true,
  },
  {
    path: "/401",
    name: "401",
    component: () => import("@/views/401.vue"),
    hidden: true,
  },
  {
    path: "/404",
    name: "404",
    component: () => import("@/views/404.vue"),
    hidden: true,
  },
];

export const asyncRoutes = [
  {
    path: "/",
    component: Layout,
    redirect: "/index",
    children: [
      {
        path: "index",
        name: "Index",
        component: () => import("@/views/index/index.vue"),
        meta: {
          title: "首页",
          icon: "home",
          affix: true,
        },
      },
    ],
  },

  {
    path: "/admin",
    component: Layout,
    redirect: "noRedirect",
    name: "Admin",
    alwaysShow: true,
    meta: { title: "管理员模块", icon: "user-filled", permissions: ["admin"] },
    children: [
      {
        path: "doctorManagement",
        name: "DoctorManagement",
        component: () => import("@/views/admin/doctorManagement.vue"),
        meta: { title: "医生管理", permissions: ["admin"] },
      },
      {
        path: "patientManagement",
        name: "PatientManagement",
        component: () => import("@/views/admin/patientManagement.vue"),
        meta: { title: "病人管理", permissions: ["admin"] },
      },
      {
        path: "departmentManagement",
        name: "DepartmentManagement",
        component: () => import("@/views/admin/departmentManagement.vue"),
        meta: { title: "科室管理", permissions: ["admin"] },
      },
      {
        path: "noticeManagement",
        name: "NoticeManagement",
        component: () => import("@/views/admin/noticeManagement.vue"),
        meta: { title: "通知公告", permissions: ["admin"] },
      },
      {
        path: "chargeRecords",
        name: "ChargeRecords",
        component: () => import("@/views/admin/chargeRecords.vue"),
        meta: { title: "收费记录查询", permissions: ["admin"] },
      },
    ],
  },

  {
    path: "/patient",
    component: Layout,
    redirect: "noRedirect",
    name: "Patient",
    alwaysShow: true,
    meta: { title: "患者服务", icon: "first-aid-kit", permissions: ["patient"] },
    children: [
      {
        path: "appointment",
        name: "Appointment",
        component: () => import("@/views/patient/appointment.vue"),
        meta: { title: "预约挂号", permissions: ["patient"] },
      },
      {
        path: "registration",
        name: "Registration",
        component: () => import("@/views/patient/registration.vue"),
        meta: { title: "现场挂号", permissions: ["patient"] },
      },
      {
        path: "charge",
        name: "PatientCharge",
        component: () => import("@/views/patient/charge.vue"),
        meta: { title: "缴费管理", permissions: ["patient"] },
      },
      {
        path: "medicalRecord",
        name: "PatientMedicalRecord",
        component: () => import("@/views/patient/medicalRecord.vue"),
        meta: { title: "病历查询", permissions: ["patient"] },
      },
      {
        path: "prescription",
        name: "PatientPrescription",
        component: () => import("@/views/patient/prescription.vue"),
        meta: { title: "处方查询", permissions: ["patient"] },
      },
      {
        path: "healthRecord",
        name: "HealthRecord",
        component: () => import("@/views/patient/healthRecord.vue"),
        meta: { title: "健康档案", permissions: ["patient"] },
      },
      {
        path: "review",
        name: "Review",
        component: () => import("@/views/patient/review.vue"),
        meta: { title: "就诊评价", permissions: ["patient"] },
      },
    ],
  },

  {
    path: "/doctor",
    component: Layout,
    redirect: "noRedirect",
    name: "Doctor",
    alwaysShow: true,
    meta: { title: "医生工作站", icon: "stamp", permissions: ["doctor", "director"] },
    children: [
      {
        path: "schedule",
        name: "DoctorSchedule",
        component: () => import("@/views/doctor/schedule.vue"),
        meta: { title: "医生排班", permissions: ["doctor", "director"] },
      },
      {
        path: "medicalRecord",
        name: "DoctorMedicalRecord",
        component: () => import("@/views/doctor/medicalRecord.vue"),
        meta: { title: "病历管理", permissions: ["doctor", "director"] },
      },
      {
        path: "prescription",
        name: "DoctorPrescription",
        component: () => import("@/views/doctor/prescription.vue"),
        meta: { title: "处方管理", permissions: ["doctor", "director"] },
      },
      {
        path: "labOrder",
        name: "LabOrder",
        component: () => import("@/views/doctor/labOrder.vue"),
        meta: { title: "检查检验申请", permissions: ["doctor", "director"] },
      },
    ],
  },

  {
    path: "/pharmacy",
    component: Layout,
    redirect: "noRedirect",
    name: "Pharmacy",
    alwaysShow: true,
    meta: { title: "药房管理", icon: "box", permissions: ["admin", "doctor", "director"] },
    children: [
      {
        path: "pharmaceutical",
        name: "Pharmaceutical",
        component: () => import("@/views/pharmacy/pharmaceutical.vue"),
        meta: { title: "药品管理", permissions: ["admin", "director"] },
      },
      {
        path: "dispense",
        name: "Dispense",
        component: () => import("@/views/pharmacy/dispense.vue"),
        meta: { title: "处方审核与发药", permissions: ["admin", "doctor", "director"] },
      },
    ],
  },

  {
    path: "/charge",
    component: Layout,
    redirect: "noRedirect",
    name: "Charge",
    alwaysShow: true,
    meta: { title: "收费管理", icon: "money", permissions: ["admin", "patient"] },
    children: [
      {
        path: "chargeList",
        name: "ChargeList",
        component: () => import("@/views/charge/chargeList.vue"),
        meta: { title: "费用管理", permissions: ["admin", "patient"] },
      },
      {
        path: "invoice",
        name: "Invoice",
        component: () => import("@/views/charge/invoice.vue"),
        meta: { title: "发票管理", permissions: ["admin"] },
      },
    ],
  },

  {
    path: "/queue",
    component: Layout,
    redirect: "noRedirect",
    name: "Queue",
    alwaysShow: true,
    meta: { title: "排队叫号", icon: "bell-filled", permissions: ["admin", "doctor", "director"] },
    children: [
      {
        path: "queueList",
        name: "QueueList",
        component: () => import("@/views/queue/queueList.vue"),
        meta: { title: "候诊队列", permissions: ["admin", "doctor", "director"] },
      },
    ],
  },

  {
    path: "/checkin",
    component: Layout,
    redirect: "noRedirect",
    name: "CheckIn",
    alwaysShow: true,
    meta: { title: "报到签到", icon: "check", permissions: ["admin", "patient"] },
    children: [
      {
        path: "checkIn",
        name: "CheckInPage",
        component: () => import("@/views/checkin/checkIn.vue"),
        meta: { title: "预约报到", permissions: ["admin", "patient"] },
      },
    ],
  },

  {
    path: "/vitalsign",
    component: Layout,
    redirect: "noRedirect",
    name: "VitalSign",
    alwaysShow: true,
    meta: { title: "护士预检", icon: "first-aid-kit", permissions: ["admin", "doctor", "director"] },
    children: [
      {
        path: "vitalSign",
        name: "VitalSignPage",
        component: () => import("@/views/vitalsign/vitalSign.vue"),
        meta: { title: "生命体征录入", permissions: ["admin", "doctor", "director"] },
      },
    ],
  },

  {
    path: "/lab",
    component: Layout,
    redirect: "noRedirect",
    name: "Lab",
    alwaysShow: true,
    meta: { title: "检验科", icon: "collection", permissions: ["admin", "doctor", "director"] },
    children: [
      {
        path: "labResult",
        name: "LabResult",
        component: () => import("@/views/lab/labResult.vue"),
        meta: { title: "检查结果录入", permissions: ["admin", "doctor", "director"] },
      },
    ],
  },

  {
    path: "/followup",
    component: Layout,
    redirect: "noRedirect",
    name: "FollowUp",
    alwaysShow: true,
    meta: { title: "复诊随访", icon: "chat-dot-round", permissions: ["doctor", "director"] },
    children: [
      {
        path: "followUp",
        name: "FollowUpPage",
        component: () => import("@/views/followup/followUp.vue"),
        meta: { title: "随访管理", permissions: ["doctor", "director"] },
      },
    ],
  },

  {
    path: "/report",
    component: Layout,
    redirect: "noRedirect",
    name: "Report",
    alwaysShow: true,
    meta: { title: "报表统计", icon: "trend-charts", permissions: ["admin", "director"] },
    children: [
      {
        path: "reports",
        name: "Reports",
        component: () => import("@/views/report/reports.vue"),
        meta: { title: "统计报表", permissions: ["admin", "director"] },
      },
    ],
  },

  {
    path: "/system",
    component: Layout,
    redirect: "noRedirect",
    name: "System",
    alwaysShow: true,
    meta: { title: "系统管理", icon: "setting", permissions: ["admin"] },
    children: [
      {
        path: "logs",
        name: "Logs",
        component: () => import("@/views/system/logs.vue"),
        meta: { title: "操作日志", permissions: ["admin"] },
      },
      {
        path: "dict",
        name: "Dict",
        component: () => import("@/views/system/dict.vue"),
        meta: { title: "数据字典", permissions: ["admin"] },
      },
      {
        path: "config",
        name: "Config",
        component: () => import("@/views/system/config.vue"),
        meta: { title: "系统参数", permissions: ["admin"] },
      },
    ],
  },

  {
    path: "/error",
    component: EmptyLayout,
    redirect: "noRedirect",
    name: "Error",
    hidden: true,
    meta: { title: "错误页", icon: "bug" },
    children: [
      {
        path: "401",
        name: "Error401",
        component: () => import("@/views/401"),
        meta: { title: "401" },
      },
      {
        path: "404",
        name: "Error404",
        component: () => import("@/views/404"),
        meta: { title: "404" },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: "/404",
    hidden: true,
  },
];

const router = createRouter({
  history: createWebHashHistory(publicPath),
  routes: constantRoutes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition;
    } else {
      return { top: 0 };
    }
  },
});

export function resetRouter() {
  try {
    router.getRoutes().forEach((route) => {
      const { name } = route;
      if (name && name !== "Login") {
        router.hasRoute(name) && router.removeRoute(name);
      }
    });
  } catch (error) {
    window.location.reload();
  }
}

export default router;
