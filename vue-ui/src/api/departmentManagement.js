import request from '@/utils/request'

export function getDepartmentList(data) {
  return request({
    url: '/departmentManagement/getList',
    method: 'post',
    data,
  })
}

export function createDepartment(data) {
  return request({
    url: '/departmentManagement/create',
    method: 'post',
    data,
  })
}
