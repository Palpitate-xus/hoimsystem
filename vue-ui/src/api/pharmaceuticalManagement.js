import request from '@/utils/request'

export function getPharmaceuticalList(data) {
  return request({
    url: '/pharmaceuticalManagement/getList',
    method: 'post',
    data,
  })
}

export function pharmaceuticalRegister(data) {
  return request({
    url: '/pharmaceuticalManagement/create',
    method: 'post',
    data,
  })
}
