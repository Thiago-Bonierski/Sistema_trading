const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function parseResponse(response) {
  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = { error: text }
    }
  }
  if (!response.ok) {
    const message =
      (body && (body.error || body.message)) ||
      `Falha na requisição (HTTP ${response.status})`
    const error = new Error(message)
    error.status = response.status
    error.body = body
    throw error
  }
  return body
}

async function get(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  return parseResponse(response)
}

async function post(path, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  })
  return parseResponse(response)
}

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, value)
    }
  })
  const suffix = search.toString()
  return suffix ? `?${suffix}` : ''
}

export const api = {
  status: () => get('/api/status'),
  live: () => get('/api/live'),

  toggleMonitor: (action) => post('/api/monitor/toggle', { action }),
  panicClose: () => post('/api/positions/close-all', {}),

  executionStatus: (refresh = false) =>
    get(`/api/execution/status${refresh ? '?refresh=true' : ''}`),
  setExecutionMode: (mode) => post('/api/execution/mode', { mode }),
  testExecutionConnection: () => post('/api/execution/test-connection', {}),

  simulate: (payload) => post('/api/simulate', payload),
  simulations: (limit = 20) => get(`/api/simulations${query({ limit })}`),
  simulation: (filename) =>
    get(`/api/simulations/${encodeURIComponent(filename)}`),

  config: () => get('/api/config'),
  saveConfig: (values) => post('/api/config', { values }),
  resetConfig: () => post('/api/config/reset', {}),

  backup: () => post('/api/backup', {}),

  mlStatus: () => get('/api/ml/status'),
  trainMl: () => post('/api/ml/train', {}),
  toggleMl: (enabled) =>
    post('/api/ml/toggle', enabled === undefined ? {} : { enabled }),

  logs: ({ lines = 300, level = '', search = '' } = {}) =>
    get(`/api/logs${query({ lines, level, search })}`),
}
