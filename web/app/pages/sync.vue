<script setup lang="ts">
interface LogItem {
  name: string
  mtime: string
  size: number
}

const { api, notify, notifyError } = useApi()
const form = reactive({
  mode: "daily",
  weekday: 1,
  hour: 4,
  minute: 0,
  interval_hours: 12,
  enabled: false,
  install: false,
})
const summary = ref("")
const jobState = ref("")
const jobStartedAt = ref("")
const liveLog = ref("还没有日志。")
const logs = ref<LogItem[]>([])
const openLogName = ref("")
const openLogText = ref("")
const liveBox = ref<HTMLElement | null>(null)
let timer = 0

const visibleLogs = computed(() => {
  if (!jobStartedAt.value) return logs.value
  return logs.value.filter(item => item.mtime < jobStartedAt.value)
})

const modeItems = [
  { label: "每天", value: "daily" },
  { label: "每隔几小时", value: "interval" },
  { label: "每周", value: "weekly" },
]
const weekdayItems = [
  { label: "周一", value: 1 },
  { label: "周二", value: 2 },
  { label: "周三", value: 3 },
  { label: "周四", value: 4 },
  { label: "周五", value: 5 },
  { label: "周六", value: 6 },
  { label: "周日", value: 0 },
]
const intervalItems = [1, 2, 3, 4, 6, 8, 12, 24].map(value => ({ label: String(value), value }))

async function loadSchedule() {
  const data = await api<Record<string, any>>("/api/settings")
  const schedule = data.schedule || {}
  form.mode = schedule.mode || "daily"
  form.hour = schedule.hour ?? 4
  form.minute = schedule.minute ?? 0
  form.interval_hours = schedule.interval_hours ?? 12
  form.weekday = schedule.weekday ?? 1
  form.enabled = Boolean(schedule.enabled)
  summary.value = schedule.enabled
    ? `已开启：${schedule.summary}`
    : `未开启自动同步。若开启，将是${schedule.summary}`
}

async function loadLogs() {
  const data = await api<{ logs: LogItem[] }>("/api/logs")
  logs.value = data.logs
}

async function saveSchedule() {
  try {
    const saved = await api<{ installed?: boolean }>("/api/schedule", {
      method: "PUT",
      body: {
        mode: form.mode,
        hour: Number(form.hour),
        minute: Number(form.minute),
        interval_hours: Number(form.interval_hours),
        weekday: Number(form.weekday),
        enabled: form.enabled,
        install: form.install,
      },
    })
    notify(saved.installed ? "时间已保存，并写入了这台机器的定时任务" : "时间已保存")
    await loadSchedule()
  } catch (error) {
    notifyError(error)
  }
}

async function toggleLog(item: LogItem) {
  if (openLogName.value === item.name) {
    openLogName.value = ""
    openLogText.value = ""
    return
  }
  try {
    const log = await api<{ text: string }>(`/api/logs/${item.name}`)
    openLogName.value = item.name
    openLogText.value = log.text || "这份日志是空的"
  } catch (error) {
    notifyError(error)
  }
}

function scrollToEnd(box: HTMLElement | null) {
  if (!box) return
  box.scrollTop = box.scrollHeight
}

async function followJob(id: string) {
  window.clearInterval(timer)
  timer = window.setInterval(async () => {
    try {
      const current = await api<{ status: string, return_code: number | null, log: string }>(`/api/jobs/${id}`)
      liveLog.value = current.log || "等待输出…"
      if (current.status === "finished") {
        window.clearInterval(timer)
        jobState.value = ""
        jobStartedAt.value = ""
        notify(
          current.return_code === 0 ? "同步已结束" : `同步失败，退出码 ${current.return_code}`,
          current.return_code === 0 ? "success" : "error",
        )
        await loadLogs()
      }
    } catch (error) {
      window.clearInterval(timer)
      notifyError(error)
    }
  }, 1000)
}

async function resumeJob() {
  const current = await api<{ id: string | null, status: string, started_at?: string, log: string }>("/api/jobs/current")
  if (current.status !== "running" || !current.id) return
  jobState.value = "正在同步"
  jobStartedAt.value = current.started_at || ""
  liveLog.value = current.log || "等待输出…"
  await followJob(current.id)
}

async function runSync() {
  try {
    const job = await api<{ id: string, started_at?: string }>("/api/sync", { method: "POST" })
    jobState.value = "正在同步"
    jobStartedAt.value = job.started_at || ""
    liveLog.value = "等待输出…"
    await followJob(job.id)
  } catch (error) {
    notifyError(error)
  }
}

watch(liveLog, async () => {
  await nextTick()
  scrollToEnd(liveBox.value)
})
watch(openLogText, async () => {
  await nextTick()
  const box = document.querySelector("[data-history-log]")
  scrollToEnd(box instanceof HTMLElement ? box : null)
})

onMounted(() => {
  Promise.all([loadSchedule(), loadLogs(), resumeJob()]).catch(notifyError)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-2xl font-semibold">
      同步
    </h1>
    <UCard>
      <form class="space-y-4" @submit.prevent="saveSchedule">
        <div class="grid gap-4 md:grid-cols-3">
          <UFormField label="重复">
            <USelect v-model="form.mode" class="w-full" :items="modeItems" />
          </UFormField>
          <UFormField v-if="form.mode === 'weekly'" label="星期">
            <USelect v-model="form.weekday" class="w-full" :items="weekdayItems" />
          </UFormField>
          <UFormField v-if="form.mode !== 'interval'" label="小时">
            <UInput v-model.number="form.hour" class="w-full" max="23" min="0" type="number" />
          </UFormField>
          <UFormField label="分钟">
            <UInput v-model.number="form.minute" class="w-full" max="59" min="0" type="number" />
          </UFormField>
          <UFormField v-if="form.mode === 'interval'" label="间隔（小时）">
            <USelect v-model="form.interval_hours" class="w-full" :items="intervalItems" />
          </UFormField>
        </div>
        <div class="flex flex-wrap gap-4">
          <UCheckbox v-model="form.enabled" label="到点自动同步" />
          <UCheckbox v-model="form.install" label="同时写入这台机器的定时任务" />
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton type="submit">
            保存时间
          </UButton>
          <UButton color="neutral" type="button" variant="outline" @click="runSync">
            立即同步一次
          </UButton>
        </div>
      </form>
      <p class="mt-3 text-sm text-muted">
        {{ summary }}
      </p>
      <p v-if="jobState" class="text-sm font-medium">
        {{ jobState }}
      </p>
      <pre ref="liveBox" class="mt-3 max-h-64 overflow-auto whitespace-pre rounded-md bg-elevated p-3 font-mono text-xs">{{ liveLog }}</pre>
    </UCard>

    <UCard>
      <template #header>
        <h2 class="font-medium">
          历史日志
        </h2>
      </template>
      <p v-if="!visibleLogs.length" class="text-sm text-muted">
        还没有历史日志。同步一次之后会出现在这里。
      </p>
      <div v-else class="space-y-2">
        <div v-for="item in visibleLogs" :key="item.name" class="rounded-md border border-default">
          <div class="flex items-center justify-between gap-3 px-3 py-2">
            <div>
              <p class="text-sm">
                {{ item.mtime }}
              </p>
              <p class="text-xs text-muted">
                {{ item.size }} 字节
              </p>
            </div>
            <UButton color="neutral" size="sm" variant="outline" @click="toggleLog(item)">
              {{ openLogName === item.name ? "收起" : "查看" }}
            </UButton>
          </div>
          <pre
            v-if="openLogName === item.name"
            data-history-log
            class="max-h-64 overflow-auto whitespace-pre border-t border-default p-3 font-mono text-xs"
          >{{ openLogText }}</pre>
        </div>
      </div>
    </UCard>
  </div>
</template>
