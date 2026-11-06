<script setup lang="ts">
interface AnimeItem {
  title?: string
  search_keyword?: string
  filename: string
  subtitle?: string
  season?: number
}

const { api, notify, notifyError } = useApi()
const anime = ref<AnimeItem[]>([])
const subtitles = ref<string[]>([])
const loading = ref(false)
const form = reactive({
  search_keyword: "",
  filename: "",
  subtitle: "",
  season_air_date: "",
  first_air_date: "",
  season: 1,
  episode_count: 12,
  language: "chs",
})

const subtitleItems = computed(() => subtitles.value.map(value => ({ label: value, value })))

async function loadAnime() {
  const data = await api<{ anime: AnimeItem[], subtitles: string[] }>("/api/anime")
  anime.value = data.anime
  subtitles.value = data.subtitles
  if (!form.subtitle && data.subtitles.length) form.subtitle = data.subtitles[0] || ""
}

async function removeAnime(item: AnimeItem) {
  try {
    const query = new URLSearchParams({ filename: item.filename, season: String(item.season || 1) })
    await api(`/api/anime?${query}`, { method: "DELETE" })
    notify("已删除订阅")
    await loadAnime()
  } catch (error) {
    notifyError(error)
  }
}

async function addAnime() {
  try {
    const body: Record<string, unknown> = {
      ...form,
      title: form.search_keyword,
      season: Number(form.season || 1),
      episode_count: Number(form.episode_count || 12),
    }
    if (!form.first_air_date) delete body.first_air_date
    await api("/api/anime", { method: "POST", body })
    notify("已加入订阅")
    form.search_keyword = ""
    form.filename = ""
    form.season_air_date = ""
    form.first_air_date = ""
    await loadAnime()
  } catch (error) {
    notifyError(error)
  }
}

onMounted(() => {
  loading.value = true
  loadAnime().catch(notifyError).finally(() => {
    loading.value = false
  })
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <h1 class="text-2xl font-semibold">
        订阅
      </h1>
      <UButton color="neutral" variant="outline" :loading="loading" @click="loadAnime().catch(notifyError)">
        刷新
      </UButton>
    </div>

    <UCard>
      <UTable
        :columns="[
          { accessorKey: 'title', header: '标题' },
          { accessorKey: 'subtitle', header: '字幕组' },
          { accessorKey: 'season', header: '季' },
          { id: 'actions', header: '' },
        ]"
        :data="anime"
        :loading="loading"
      >
        <template #title-cell="{ row }">
          {{ row.original.title || row.original.search_keyword || "未命名" }}
        </template>
        <template #actions-cell="{ row }">
          <div class="text-right">
            <UButton color="neutral" size="sm" variant="outline" @click="removeAnime(row.original)">
              删除
            </UButton>
          </div>
        </template>
      </UTable>
    </UCard>

    <UCard>
      <template #header>
        <h2 class="font-medium">
          手动添加
        </h2>
      </template>
      <form class="grid gap-4 md:grid-cols-2" @submit.prevent="addAnime">
        <UFormField label="标题" required>
          <UInput v-model="form.search_keyword" class="w-full" required />
        </UFormField>
        <UFormField label="文件名" required>
          <UInput v-model="form.filename" class="w-full" required />
        </UFormField>
        <UFormField label="字幕组" required>
          <USelect v-model="form.subtitle" class="w-full" :items="subtitleItems" />
        </UFormField>
        <UFormField label="本季开播" required>
          <UInput v-model="form.season_air_date" class="w-full" required type="date" />
        </UFormField>
        <UFormField label="系列首播">
          <UInput v-model="form.first_air_date" class="w-full" type="date" />
        </UFormField>
        <UFormField label="季数">
          <UInput v-model.number="form.season" class="w-full" min="1" type="number" />
        </UFormField>
        <UFormField label="集数">
          <UInput v-model.number="form.episode_count" class="w-full" min="1" type="number" />
        </UFormField>
        <UFormField label="语言">
          <UInput v-model="form.language" class="w-full" />
        </UFormField>
        <div class="md:col-span-2">
          <UButton type="submit">
            加入订阅
          </UButton>
        </div>
      </form>
    </UCard>
  </div>
</template>
