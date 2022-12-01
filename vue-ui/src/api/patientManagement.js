import request from '@/utils/request'

export function getList(data) {
  return request({
    url: '/patientManagement/getList',
    method: 'post',
    data,
  })
}

export function doEdit(data) {
    return request({
      url: '/patientManagement/doEdit',
      method: 'post',
      data,
    })
}

export function doDelete(data) {
    return request({
      url: '/patientManagement/doDelete',
      method: 'post',
      data,
    })
}