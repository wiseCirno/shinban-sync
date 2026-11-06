export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export function useNeedToken() {
  return useState("shinban-need-token", () => false)
}

export function useApi() {
  const needToken = useNeedToken()
  const toast = useToast()

  function notify(title: string, color: "success" | "warning" | "error" = "success") {
    toast.add({ title, color })
  }

  function notifyError(error: unknown) {
    const message = error instanceof Error ? error.message : "请求失败"
    const warning = message.includes("已存在") || message.includes("没有")
    notify(message, warning ? "warning" : "error")
  }

  async function api<T>(path: string, options: { method?: string, body?: unknown } = {}): Promise<T> {
    const token = import.meta.client ? sessionStorage.getItem("shinban-token") : ""
    try {
      const data = await $fetch<T>(path, {
        method: (options.method || "GET") as "GET",
        body: options.body as Record<string, unknown> | undefined,
        headers: token ? { "X-Shinban-Token": token } : undefined,
      })
      needToken.value = false
      return data
    } catch (error) {
      const status = Number((error as { statusCode?: number }).statusCode || 0)
      const detail = (error as { data?: { detail?: string } }).data?.detail
      if (status === 401) needToken.value = true
      throw new ApiError(detail || "请求失败", status)
    }
  }

  return { api, notify, notifyError }
}
