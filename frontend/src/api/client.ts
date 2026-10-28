import axios from 'axios'

// API key is injected per-request from the store — see useApiKey()
const client = axios.create({
  baseURL: '/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Request interceptor: inject X-API-Key from localStorage if present
client.interceptors.request.use((config) => {
  const key = localStorage.getItem('api_key') ?? sessionStorage.getItem('api_key')
  if (key) {
    config.headers['X-API-Key'] = key
  }
  return config
})

export default client
