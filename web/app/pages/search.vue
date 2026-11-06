<script setup lang="ts">
interface Show {
  id: number
  name: string
  original_name?: string
  poster_url?: string
}

interface Season {
  name: string
  season_number: number
  air_date?: string
  episode_count?: number
}

interface Group {
  name: string
  latest_episode?: number | string | null
}

const { api, notify, notifyError } = useApi()
const query = ref("")
const busy = ref("")
const shows = ref<Show[]>([])
const seasons = ref<Season[]>([])
const groups = ref<Group[]>([])
const level = ref<"shows" | "season" | "group">("shows")
const pickedShow = ref<Show | null>(null)
const pickedSeason = ref<Season | null>(null)

function clearSearch() {
  query.value = ""
  shows.value = []
  seasons.value = []
  groups.value = []
  pickedShow.value = null
  pickedSeason.value = null
  level.value = "shows"
}

async function search() {
  busy.value = "正在搜索番剧…"
  try {
    const data = await api<{ results: Show[] }>(`/api/search?q=${encodeURIComponent(query.value)}`)
    pickedShow.value = null
    pickedSeason.value = null
    seasons.value = []
    groups.value = []
    shows.value = data.results
    level.value = "shows"
    if (!data.results.length) notify("没有找到相关番剧", "warning")
  } catch (error) {
    notifyError(error)
  } finally {
    busy.value = ""
  }
}

async function pickShow(show: Show) {
  busy.value = "正在读取季度…"
  try {
    const detail = await api<{ seasons: Season[] }>(`/api/series/${show.id}`)
    pickedShow.value = show
    pickedSeason.value = null
    groups.value = []
    seasons.value = detail.seasons || []
    level.value = "season"
  } catch (error) {
    notifyError(error)
  } finally {
    busy.value = ""
  }
}

async function pickSeason(show: Show, season: Season) {
  busy.value = "正在检索字幕组…"
  try {
    const found = await api<{ groups: Group[] }>(`/api/series/${show.id}/seasons/${season.season_number}/groups`)
    pickedSeason.value = season
    groups.value = found.groups || []
    level.value = "group"
    if (!groups.value.length) notify("这一季还没有匹配到支持的字幕组", "warning")
  } catch (error) {
    notifyError(error)
  } finally {
    busy.value = ""
  }
}

async function subscribe(show: Show, season: Season, group: Group) {
  busy.value = "正在加入订阅…"
  try {
    await api("/api/subscriptions", {
      method: "POST",
      body: { series_id: show.id, season_number: season.season_number, subtitle: group.name },
    })
    notify("已加入订阅")
    clearSearch()
  } catch (error) {
    notifyError(error)
  } finally {
    busy.value = ""
  }
}
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-2xl font-semibold">
      搜索番剧
    </h1>
    <form class="flex max-w-xl items-center gap-2" @submit.prevent="search">
      <UInput v-model="query" class="flex-1" placeholder="输入中文或原名" required />
      <UButton :loading="busy === '正在搜索番剧…'" type="submit">
        搜索
      </UButton>
    </form>

    <div v-if="busy" class="flex items-center gap-2 text-sm font-medium">
      <UIcon class="size-4 animate-spin" name="i-lucide-loader-circle" />
      {{ busy }}
    </div>

    <UBreadcrumb
      v-if="pickedShow"
      :items="[
        { label: '搜索结果', onSelect: () => { level = 'shows' } },
        ...(level === 'group' && pickedSeason
          ? [
            { label: pickedShow.name, onSelect: () => { level = 'season' } },
            { label: pickedSeason.name },
          ]
          : [{ label: pickedShow.name }]),
      ]"
    />

    <div v-if="level === 'shows'" class="flex flex-wrap gap-3" :class="{ 'pointer-events-none opacity-50': busy }">
      <UCard v-for="show in shows" :key="show.id" class="w-36" :ui="{ body: 'p-2 sm:p-2' }">
        <img
          v-if="show.poster_url"
          :alt="show.name"
          class="h-52 w-full rounded-md object-cover object-top"
          :src="show.poster_url"
        >
        <p class="mt-2 line-clamp-2 text-sm font-medium">
          {{ show.name }}
        </p>
        <p class="line-clamp-2 text-xs text-muted">
          {{ show.original_name }}
        </p>
        <UButton class="mt-2" block size="xs" @click="pickShow(show)">
          选择
        </UButton>
      </UCard>
    </div>

    <UCard v-if="level === 'season'">
      <template #header>
        <h2 class="text-base font-medium">
          选择季度
        </h2>
      </template>
      <div class="flex flex-col gap-2">
        <UButton
          v-for="season in seasons"
          :key="season.season_number"
          class="justify-start"
          color="neutral"
          variant="outline"
          @click="pickedShow && pickSeason(pickedShow, season)"
        >
          {{ season.name }} · {{ season.air_date || "日期未知" }} · {{ season.episode_count || 0 }} 集
        </UButton>
      </div>
    </UCard>

    <UCard v-if="level === 'group'">
      <template #header>
        <h2 class="text-base font-medium">
          选择字幕组
        </h2>
      </template>
      <div class="flex flex-col gap-2">
        <UButton
          v-for="group in groups"
          :key="group.name"
          class="justify-start"
          color="neutral"
          variant="outline"
          @click="pickedShow && pickedSeason && subscribe(pickedShow, pickedSeason, group)"
        >
          {{ group.name }} · 最新 {{ group.latest_episode ?? "未知" }} 集
        </UButton>
      </div>
    </UCard>
  </div>
</template>
