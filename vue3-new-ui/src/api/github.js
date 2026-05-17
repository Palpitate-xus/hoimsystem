import request from 'axios'

export function getRepos(params) {
  return request({
    url: '',
    method: 'get',
    params,
    timeout: 10000,
  })
}

export function getStargazers(params) {
  return request({
    url: '',
    method: 'get',
    params,
    timeout: 10000,
  })
}
