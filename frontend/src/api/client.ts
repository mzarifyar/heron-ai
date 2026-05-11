import axios from 'axios'

const api = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // Normalize error messages
    const message =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message ??
      'Unknown error'
    return Promise.reject(new Error(String(message)))
  },
)

export default api
