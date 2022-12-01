import request from '@/utils/request'

export function getList(data) {
  return request({
    url: '/doctorManagement/getList',
    method: 'post',
    data,
  })
}

export function doEdit(data) {
  return request({
    url: '/doctorManagement/doEdit',
    method: 'post',
    data,
  })
}

export function doDelete(data) {
  return request({
    url: '/doctorManagement/doDelete',
    method: 'post',
    data,
  })
}
