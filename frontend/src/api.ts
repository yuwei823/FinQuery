import type { AuthUser, GuestLoginResponse, LoginResponse, ProgressEvent, PublicConfig, QueryResult, SavedMemory, SchemaField, SchemaTable, WorkspaceConfig } from "./types"

const API_BASE = import.meta.env.VITE_API_BASE ?? ""
const TOKEN_KEY = "finquery_access_token"
const GUEST_ID_KEY = "finquery_guest_id"

function token() {
  return sessionStorage.getItem(TOKEN_KEY)
}

function guestId() {
  let value = localStorage.getItem(GUEST_ID_KEY)
  if (!value) {
    value = crypto.randomUUID()
    localStorage.setItem(GUEST_ID_KEY, value)
  }
  return value
}

async function request<T>(path: string, options?: RequestInit, timeoutMs = 90_000): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
        ...options?.headers,
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求处理超时，后端可能仍在构建Schema索引或等待模型响应")
    }
    throw new Error("无法连接后端服务，请先启动 FastAPI（127.0.0.1:8000）")
  } finally {
    window.clearTimeout(timeout)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? "服务暂时不可用")
  }
  return response.json() as Promise<T>
}

async function streamQuery(
  queryText: string,
  workspace: WorkspaceConfig,
  sessionId: string,
  onProgress?: (event: ProgressEvent) => void,
): Promise<QueryResult> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 300_000)
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/query`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      },
      body: JSON.stringify({ query: queryText, session_id: sessionId, workspace }),
    })
  } catch (error) {
    window.clearTimeout(timeout)
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求处理超时，后端可能仍在构建Schema索引或等待模型响应")
    }
    throw new Error("无法连接后端服务，请先启动 FastAPI（127.0.0.1:8000）")
  }
  const contentType = response.headers.get("content-type") ?? ""
  if (!response.ok || !contentType.includes("text/event-stream")) {
    window.clearTimeout(timeout)
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? "服务暂时不可用")
  }
  try {
    const reader = response.body?.getReader()
    if (!reader) throw new Error("当前浏览器不支持流式响应")
    const decoder = new TextDecoder()
    let buffer = ""
    let result: QueryResult | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split("\n\n")
      buffer = blocks.pop() ?? ""
      for (const block of blocks) {
        let eventName = ""
        let data = ""
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) eventName = line.slice(7)
          else if (line.startsWith("data: ")) data = line.slice(6)
        }
        if (!eventName || !data) continue
        const payload = JSON.parse(data)
        if (eventName === "progress") onProgress?.(payload as ProgressEvent)
        else if (eventName === "result") result = payload as QueryResult
      }
    }
    if (!result) throw new Error("服务连接中断，未收到查询结果")
    return result
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求处理超时，后端可能仍在构建Schema索引或等待模型响应")
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export const api = {
  hasSession: () => Boolean(token()),
  publicConfig: () => request<PublicConfig>("/api/public-config"),
  login: async (username: string, password: string) => {
    const result = await request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    })
    sessionStorage.setItem(TOKEN_KEY, result.access_token)
    return result.user
  },
  guestLogin: async () => {
    const result = await request<GuestLoginResponse>("/api/auth/guest", {
      method: "POST",
      body: JSON.stringify({ guest_id: guestId() }),
    })
    sessionStorage.setItem(TOKEN_KEY, result.access_token)
    return result
  },
  me: () => request<AuthUser>("/api/auth/me"),
  logout: async () => {
    try {
      if (token()) await request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" })
    } finally {
      sessionStorage.removeItem(TOKEN_KEY)
    }
  },
  clearSession: () => sessionStorage.removeItem(TOKEN_KEY),
  schema: () => request<SchemaTable[]>("/api/schema"),
  query: (query: string, workspace: WorkspaceConfig, sessionId: string, onProgress?: (event: ProgressEvent) => void) =>
    streamQuery(query, workspace, sessionId, onProgress),
  clarify: (taskId: string, optionId: string) =>
    request<QueryResult>(`/api/tasks/${taskId}/clarify`, {
      method: "POST",
      body: JSON.stringify({ option_id: optionId }),
    }, 300_000),
  save: (taskId: string) =>
    request<{ saved: boolean }>("/api/memories", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId }),
    }),
  memories: () => request<SavedMemory[]>("/api/memories"),
  saveField: (tableId: string, field: SchemaField) =>
    request<{ saved: boolean }>("/api/memories/fields", {
      method: "POST",
      body: JSON.stringify({
        table_id: tableId,
        name: field.name,
        label: field.label,
        field_type: field.type,
      }),
    }),
  deleteMemory: (memoryId: string) =>
    request<{ deleted: boolean }>(`/api/memories/${encodeURIComponent(memoryId)}`, {
      method: "DELETE",
    }),
}
