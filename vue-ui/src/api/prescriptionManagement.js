import request from '@/utils/request'

export function getPrescriptionList(data) {
  return request({
    url: '/prescriptionManagement/getList',
    method: 'post',
    data,
  })
}

export function prescriptionRegister(data) {
  return request({
    url: '/prescriptionManagement/create',
    method: 'post',
    data,
  })
}
