/**
 * @description router全局配置，如有必要可分文件抽离，其中asyncRoutes只有在intelligence模式下才会用到
 */

import Vue from 'vue'
import VueRouter from 'vue-router'
import Layout from '@/layouts'
import EmptyLayout from '@/layouts/EmptyLayout'
import { publicPath, routerMode } from '@/config'

Vue.use(VueRouter)
export const constantRoutes = [
  {
    path: '/login',
    component: () => import('@/views/login/index'),
    hidden: true,
  },
  {
    path: '/register',
    component: () => import('@/views/register/index'),
    hidden: true,
  },
  {
    path: '/401',
    name: '401',
    component: () => import('@/views/401'),
    hidden: true,
  },
  {
    path: '/404',
    name: '404',
    component: () => import('@/views/404'),
    hidden: true,
  },
]

export const asyncRoutes = [
  {
    path: '/',
    component: Layout,
    redirect: '/index',
    children: [
      {
        path: 'index',
        name: 'Index',
        component: () => import('@/views/admin/index'),
        meta: {
          title: '首页',
          icon: 'home',
          affix: true,
          permissions: ['admin', 'editor'],
        },
      },
    ],
  },
  {
    path: '/',
    component: Layout,
    redirect: '/index',
    children: [
      {
        path: 'index',
        name: 'Index',
        component: () => import('@/views/workspace/index'),
        meta: {
          title: '首页',
          icon: 'home',
          affix: true,
          permissions: ['doctor', 'director'],
        },
      },
    ],
  },
  {
    path: '/',
    component: Layout,
    redirect: '/index',
    children: [
      {
        path: 'index',
        name: 'Index',
        component: () => import('@/views/patient/index'),
        meta: {
          title: '首页',
          icon: 'home',
          affix: true,
          permissions: ['patient'],
        },
      },
    ],
  },
  {
    path: '/settings',
    component: Layout,
    redirect: 'noRedirect',
    children: [
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/admin/settings'),
        meta: {
          title: '全局设置',
          icon: 'marker',
          permissions: ['admin'],
        },
      },
    ],
  },
  {
    path: '/doctor',
    component: Layout,
    redirect: 'noRedirect',
    meta: {
      title: '处方与检查',
      icon: 'users-cog',
      permissions: ['doctor', 'director'],
    },
    children: [
      {
        path: 'prescriptionRegister',
        name: 'prescriptionRegister',
        component: () => import('@/views/prescriptionManagement/doctor'),
        meta: {
          title: '写处方',
          icon: 'marker',
          affix: true,
          permissions: ['doctor', 'director'],
        },
      },
      {
        path: 'inspectionRegister',
        name: 'inspectionRegister',
        component: () => import('@/views/inspectionManagement/doctor'),
        meta: {
          title: '开检查',
          icon: 'marker',
          affix: true,
          permissions: ['doctor', 'director'],
        },
      },
      {
        path: 'prescriptionManagement',
        name: 'prescriptionManagement',
        component: () => import('@/views/prescriptionManagement/index'),
        meta: {
          title: '处方管理',
          icon: 'marker',
          permissions: ['doctor', 'director'],
        },
      },
    ],
  },
  {
    path: '/Management',
    component: Layout,
    redirect: 'noRedirect',
    name: 'adminManagement',
    meta: {
      title: '管理工具',
      icon: 'users-cog',
      permissions: ['admin', 'director'],
    },
    children: [
      {
        path: 'departmentManagement',
        name: 'departmentManagement',
        component: EmptyLayout,
        meta: {
          title: '科室管理',
          icon: 'marker',
          permissions: ['admin'],
        },
        children: [
          {
            path: 'departmentManagementtest',
            name: 'departmentManagementtest',
            component: () => import('@/views/departmentManagement/index'),
            meta: {
              title: '科室管理',
              icon: 'marker',
              permissions: ['admin'],
            },
          },
          {
            path: 'departmentRegister',
            name: 'departmentRegister',
            // eslint-disable-next-line
            component: () => import('@/views/departmentManagement/departmentRegister'),
            meta: {
              title: '科室注册',
              icon: 'marker',
              permissions: ['admin'],
            },
          },
        ],
      },
      {
        path: '/doctorManagement',
        name: 'doctorManagement',
        component: EmptyLayout,
        meta: {
          title: '医生管理',
          icon: 'marker',
          permissions: ['admin', 'director'],
        },
        redirect: 'noRedirect',
        children: [
          {
            path: 'doctorRegister',
            name: 'doctorRegister',
            component: () => import('@/views/doctorManagement/doctorRegister'),
            meta: {
              title: '医生注册',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
          {
            path: 'doctorManagementtest',
            name: 'doctorManagementtest',
            component: () => import('@/views/doctorManagement/index'),
            meta: {
              title: '医生管理',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
        ],
      },
      {
        path: 'doctorScheduleRegister',
        name: 'doctorScheduleRegister',
        component: EmptyLayout,
        meta: {
          title: '医生排班',
          icon: 'marker',
          permissions: ['admin', 'director'],
        },
        children: [
          {
            path: 'doctorScheduleRegister',
            name: 'doctorScheduleRegister',
            component: () =>
              import('@/views/doctorScheduleManagement/doctorScheduleRegister'),
            meta: {
              title: '医生排班',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
          {
            path: 'doctorScheduleManagement',
            name: 'doctorScheduleManagement',
            component: () => import('@/views/doctorScheduleManagement/index'),
            meta: {
              title: '医生排班管理',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
        ],
      },
      {
        path: 'patientManagement',
        name: 'patientManagement',
        component: () => import('@/views/patientManagement/index'),
        meta: {
          title: '病人管理',
          icon: 'marker',
          permissions: ['admin', 'doctor'],
        },
      },
      {
        path: 'pharmaceuticalManagement',
        name: 'pharmaceuticalManagement',
        component: EmptyLayout,
        meta: {
          title: '药品管理',
          icon: 'marker',
          permissions: ['admin', 'director'],
        },
        children: [
          {
            path: 'pharmaceuticalManagement',
            name: 'pharmaceuticalManagement',
            component: () => import('@/views/pharmaceuticalManagement/index'),
            meta: {
              title: '药品管理',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
          {
            path: 'pharmaceuticalRegister',
            name: 'pharmaceuticalRegister',
            component: () =>
              import('@/views/pharmaceuticalManagement/pharmaceuticalRegister'),
            meta: {
              title: '药品注册',
              icon: 'marker',
              permissions: ['admin', 'director'],
            },
          },
        ],
      },
    ],
  },
  {
    path: '/notice',
    name: 'notice',
    component: Layout,
    redirect: 'noRedirect',
    meta: {
      title: '通知管理',
      icon: 'marker',
      permissions: ['admin', 'director'],
    },
    children: [
      {
        path: 'noticeManagement',
        name: 'noticeManagement',
        component: () => import('@/views/noticeManagement/index'),
        meta: {
          title: '通知管理',
          icon: 'marker',
          permissions: ['admin', 'director'],
        },
      },
      {
        path: 'noticeRegister',
        name: 'noticeRegister',
        component: () => import('@/views/noticeManagement/noticeRegister'),
        meta: {
          title: '通知发布',
          icon: 'marker',
          permissions: ['admin', 'director'],
        },
      },
    ],
  },
  {
    path: '/patient',
    component: Layout,
    redirect: 'noRedirect',
    name: 'patient',
    meta: { title: '预约挂号', icon: 'users-cog', permissions: ['patient'] },
    children: [
      {
        path: '/registrationManagement',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'registrationManagement',
            name: 'registrationManagement',
            component: () => import('@/views/registrationManagement/index'),
            meta: {
              title: '挂号',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/registrationRecords',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'registrationRecords',
            name: 'registrationRecords',
            component: () => import('@/views/registrationManagement/records'),
            meta: {
              title: '挂号记录',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/appointmentManagement',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'appointmentManagement',
            name: 'appointmentManagement',
            component: () => import('@/views/appointmentManagement/index'),
            meta: {
              title: '预约',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/appointmentRecords',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'appointmentRecords',
            name: 'appointmentRecords',
            component: () => import('@/views/appointmentManagement/records'),
            meta: {
              title: '预约记录',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
    ],
  },
  {
    path: '/patientinfo',
    component: Layout,
    redirect: 'noRedirect',
    name: 'patientinfo',
    meta: { title: 'message', icon: 'users-cog', permissions: ['patient'] },
    children: [
      {
        path: '/advicePatient',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'advicePatient',
            name: 'advicePatient',
            component: () => import('@/views/adviceManagement/patient'),
            meta: {
              title: '医嘱',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/inspectionPatient',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'inspectionPatient',
            name: 'inspectionPatient',
            component: () => import('@/views/inspectionManagement/patient'),
            meta: {
              title: '检查结果',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/priscriptionPatient',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'priscriptionPatient',
            name: 'priscriptionPatient',
            component: () => import('@/views/prescriptionManagement/patient'),
            meta: {
              title: '处方',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
      {
        path: '/medicalRecordsManagement',
        component: EmptyLayout,
        redirect: 'noRedirect',
        children: [
          {
            path: 'medicalRecordsPatient',
            name: 'medicalRecordsPatient',
            component: () => import('@/views/medicalRecordsManagement/patient'),
            meta: {
              title: '病历',
              icon: 'marker',
              permissions: ['patient'],
            },
          },
        ],
      },
    ],
  },
  {
    path: '/chargesPatient',
    component: Layout,
    redirect: 'noRedirect',
    children: [
      {
        path: 'chargesPatient',
        name: 'chargesPatient',
        component: () => import('@/views/chargesManagement/patient'),
        meta: {
          title: '收费',
          icon: 'marker',
          permissions: ['patient'],
        },
      },
    ],
  },
  // {
  //   path: '/vab',
  //   component: Layout,
  //   redirect: 'noRedirect',
  //   name: 'Vab',
  //   alwaysShow: true,
  //   meta: { title: '组件', icon: 'box-open' },
  //   children: [
  //     {
  //       path: 'permissions',
  //       name: 'Permission',
  //       component: () => import('@/views/vab/permissions/index'),
  //       meta: {
  //         title: '角色权限',
  //         permissions: ['admin', 'editor', 'doctor', 'patient'],
  //       },
  //     },
  //     {
  //       path: 'icon',
  //       component: EmptyLayout,
  //       redirect: 'noRedirect',
  //       name: 'Icon',
  //       meta: {
  //         title: '图标',
  //         permissions: ['admin'],
  //       },
  //       children: [
  //         {
  //           path: 'awesomeIcon',
  //           name: 'AwesomeIcon',
  //           component: () => import('@/views/vab/icon/index'),
  //           meta: { title: '常规图标' },
  //         },
  //         {
  //           path: 'colorfulIcon',
  //           name: 'ColorfulIcon',
  //           component: () => import('@/views/vab/icon/colorfulIcon'),
  //           meta: { title: '多彩图标' },
  //         },
  //       ],
  //     },
  //     {
  //       path: 'table',
  //       component: () => import('@/views/vab/table/index'),
  //       name: 'Table',
  //       meta: {
  //         title: '表格',
  //         permissions: ['admin'],
  //       },
  //     },
  //     {
  //       path: 'map',
  //       component: () => import('@/views/vab/map/index'),
  //       name: 'Map',
  //       meta: {
  //         title: '地图',
  //         permissions: ['admin'],
  //       },
  //     },

  //     {
  //       path: 'webSocket',
  //       name: 'WebSocket',
  //       component: () => import('@/views/vab/webSocket/index'),
  //       meta: { title: 'webSocket', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'form',
  //       name: 'Form',
  //       component: () => import('@/views/vab/form/index'),
  //       meta: { title: '表单', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'element',
  //       name: 'Element',
  //       component: () => import('@/views/vab/element/index'),
  //       meta: { title: '常用组件', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'tree',
  //       name: 'Tree',
  //       component: () => import('@/views/vab/tree/index'),
  //       meta: { title: '树', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'verify',
  //       name: 'Verify',
  //       component: () => import('@/views/vab/verify/index'),
  //       meta: { title: '验证码', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'menu1',
  //       component: () => import('@/views/vab/nested/menu1/index'),
  //       name: 'Menu1',
  //       alwaysShow: true,
  //       meta: {
  //         title: '嵌套路由 1',
  //         permissions: ['admin'],
  //       },
  //       children: [
  //         {
  //           path: 'menu1-1',
  //           name: 'Menu1-1',
  //           alwaysShow: true,
  //           meta: { title: '嵌套路由 1-1' },
  //           component: () => import('@/views/vab/nested/menu1/menu1-1/index'),

  //           children: [
  //             {
  //               path: 'menu1-1-1',
  //               name: 'Menu1-1-1',
  //               meta: { title: '嵌套路由 1-1-1' },
  //               component: () =>
  //                 import('@/views/vab/nested/menu1/menu1-1/menu1-1-1/index'),
  //             },
  //           ],
  //         },
  //       ],
  //     },
  //     {
  //       path: 'magnifier',
  //       name: 'Magnifier',
  //       component: () => import('@/views/vab/magnifier/index'),
  //       meta: { title: '放大镜', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'loading',
  //       name: 'Loading',
  //       component: () => import('@/views/vab/loading/index'),
  //       meta: { title: 'loading', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'player',
  //       name: 'Player',
  //       component: () => import('@/views/vab/player/index'),
  //       meta: { title: '视频播放器', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'markdownEditor',
  //       name: 'MarkdownEditor',
  //       component: () => import('@/views/vab/markdownEditor/index'),
  //       meta: { title: 'markdown编辑器', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'editor',
  //       name: 'Editor',
  //       component: () => import('@/views/vab/editor/index'),
  //       meta: {
  //         title: '富文本编辑器',
  //         permissions: ['admin'],
  //         badge: 'New',
  //       },
  //     },
  //     {
  //       path: 'backToTop',
  //       name: 'BackToTop',
  //       component: () => import('@/views/vab/backToTop/index'),
  //       meta: { title: '返回顶部', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'lodash',
  //       name: 'Lodash',
  //       component: () => import('@/views/vab/lodash/index'),
  //       meta: { title: 'lodash', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'smallComponents',
  //       name: 'SmallComponents',
  //       component: () => import('@/views/vab/smallComponents/index'),
  //       meta: { title: '小组件', permissions: ['admin'] },
  //     },

  //     {
  //       path: 'upload',
  //       name: 'Upload',
  //       component: () => import('@/views/vab/upload/index'),
  //       meta: { title: '上传', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'log',
  //       name: 'Log',
  //       component: () => import('@/views/vab/errorLog/index'),
  //       meta: { title: '错误日志模拟', permissions: ['admin'] },
  //     },
  //     {
  //       path: 'https://github.com/chuzhixin/vue-admin-beautiful?utm_source=gold_browser_extension',
  //       name: 'ExternalLink',
  //       meta: {
  //         title: '外链',
  //         target: '_blank',
  //         permissions: ['admin', 'editor'],
  //         badge: 'New',
  //       },
  //     },
  //     {
  //       path: 'more',
  //       name: 'More',
  //       component: () => import('@/views/vab/more/index'),
  //       meta: { title: '关于', permissions: ['admin'] },
  //     },
  //   ],
  // },
  // {
  //   path: '/personnelManagement',
  //   component: Layout,
  //   redirect: 'noRedirect',
  //   name: 'PersonnelManagement',
  //   meta: { title: '配置', icon: 'users-cog', permissions: ['admin'] },
  //   children: [
  //     {
  //       path: 'userManagement',
  //       name: 'UserManagement',
  //       component: () =>
  //         import('@/views/personnelManagement/userManagement/index'),
  //       meta: { title: '用户管理' },
  //     },
  //     {
  //       path: 'roleManagement',
  //       name: 'RoleManagement',
  //       component: () =>
  //         import('@/views/personnelManagement/roleManagement/index'),
  //       meta: { title: '角色管理' },
  //     },
  //     {
  //       path: 'menuManagement',
  //       name: 'MenuManagement',
  //       component: () =>
  //         import('@/views/personnelManagement/menuManagement/index'),
  //       meta: { title: '菜单管理', badge: 'New' },
  //     },
  //   ],
  // },
  // {
  //   path: '/mall',
  //   component: Layout,
  //   redirect: 'noRedirect',
  //   name: 'Mall',
  //   meta: {
  //     title: '商城',
  //     icon: 'shopping-cart',
  //     permissions: ['admin'],
  //   },

  //   children: [
  //     {
  //       path: 'pay',
  //       name: 'Pay',
  //       component: () => import('@/views/mall/pay/index'),
  //       meta: {
  //         title: '支付',
  //         noKeepAlive: true,
  //       },
  //       children: null,
  //     },
  //     {
  //       path: 'goodsList',
  //       name: 'GoodsList',
  //       component: () => import('@/views/mall/goodsList/index'),
  //       meta: {
  //         title: '商品列表',
  //       },
  //     },
  //   ],
  // },
  // {
  //   path: '/error',
  //   component: EmptyLayout,
  //   redirect: 'noRedirect',
  //   name: 'Error',
  //   meta: { title: '错误页', icon: 'bug' },
  //   children: [
  //     {
  //       path: '401',
  //       name: 'Error401',
  //       component: () => import('@/views/401'),
  //       meta: { title: '401' },
  //     },
  //     {
  //       path: '404',
  //       name: 'Error404',
  //       component: () => import('@/views/404'),
  //       meta: { title: '404' },
  //     },
  //   ],
  // },
  {
    path: '*',
    redirect: '/404',
    hidden: true,
  },
]

const router = new VueRouter({
  base: publicPath,
  mode: routerMode,
  scrollBehavior: () => ({
    y: 0,
  }),
  routes: constantRoutes,
})

export function resetRouter() {
  location.reload()
}

export default router
