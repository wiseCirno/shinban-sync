<script setup lang="ts">
const route = useRoute()
const needToken = useNeedToken()
const token = ref("")
const menuOpen = ref(false)

const items = [
  { label: "订阅", to: "/" },
  { label: "搜索", to: "/search" },
  { label: "配置", to: "/settings" },
  { label: "同步", to: "/sync" },
]

watch(() => route.path, () => {
  menuOpen.value = false
})

function saveToken() {
  sessionStorage.setItem("shinban-token", token.value.trim())
  needToken.value = false
  reloadNuxtApp()
}
</script>

<template>
  <UHeader
    v-model:open="menuOpen"
    :ui="{ toggle: 'lg:hidden', center: 'hidden lg:flex' }"
  >
    <template #left>
      <NuxtLink class="flex items-center gap-2 text-lg font-semibold" to="/">
        <img alt="" class="size-10 rounded-full" src="/icon.png">
        Shinban Sync
      </NuxtLink>
    </template>
    <UNavigationMenu :items="items" />
    <template #body>
      <UNavigationMenu class="w-full" orientation="vertical" :items="items" />
    </template>
  </UHeader>

  <UContainer class="py-6">
    <UAlert
      v-if="needToken"
      class="mb-4"
      color="warning"
      title="需要 Web 令牌"
      description="配置里设置了访问令牌。填入后才会继续请求。"
    >
      <template #actions>
        <div class="flex gap-2">
          <UInput v-model="token" class="w-56" placeholder="Web 令牌" type="password" />
          <UButton @click="saveToken">
            使用
          </UButton>
        </div>
      </template>
    </UAlert>
    <slot />
  </UContainer>
</template>
