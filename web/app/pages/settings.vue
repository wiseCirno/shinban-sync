<script setup lang="ts">
const { api, notify, notifyError } = useApi()
const configPath = ref("")
const secrets = reactive({
  telegram: false,
  tmdb: false,
  aria2: false,
  sftp: false,
  openlist: false,
  web: false,
})
const form = reactive({
  telegram_bot_token: "",
  telegram_user_id: "",
  tmdb_token: "",
  aria2_base_url: "",
  aria2_token: "",
  provider: "local",
  folder_name_pattern: "",
  video_name_pattern: "",
  local_aria2_path: "",
  local_target_path: "",
  sftp_host: "",
  sftp_port: 22,
  sftp_user: "",
  sftp_password: "",
  sftp_pub_key: "",
  sftp_aria2_path: "",
  sftp_target_path: "",
  openlist_base_url: "",
  openlist_user: "",
  openlist_password: "",
  openlist_aria2_path: "",
  openlist_target_path: "",
  web_host: "",
  web_port: 3325,
  web_token: "",
})

const providerItems = [
  { label: "本地目录", value: "local" },
  { label: "SFTP", value: "sftp" },
  { label: "OpenList", value: "openlist" },
]
const providerHint = computed(() => {
  const names: Record<string, string> = { local: "本地目录", sftp: "SFTP", openlist: "OpenList" }
  return `现在整理到${names[form.provider] || form.provider}。其余方式已变灰，不用填。`
})

function secretPlaceholder(enabled: boolean, example: string) {
  return enabled ? "已设置，留空不修改" : example
}

async function loadSettings() {
  const data = await api<Record<string, any>>("/api/settings")
  form.telegram_user_id = data.telegram_user_id || ""
  form.aria2_base_url = data.downloader?.aria2?.base_url || ""
  form.provider = data.storage?.provider || "local"
  form.folder_name_pattern = data.storage?.folder_name_pattern || ""
  form.video_name_pattern = data.storage?.video_name_pattern || ""
  form.local_aria2_path = data.storage?.local?.aria2_path || ""
  form.local_target_path = data.storage?.local?.target_path || ""
  form.sftp_host = data.storage?.sftp?.host || ""
  form.sftp_port = data.storage?.sftp?.port || 22
  form.sftp_user = data.storage?.sftp?.user || ""
  form.sftp_pub_key = data.storage?.sftp?.pub_key || ""
  form.sftp_aria2_path = data.storage?.sftp?.aria2_path || ""
  form.sftp_target_path = data.storage?.sftp?.target_path || ""
  form.openlist_base_url = data.storage?.openlist?.base_url || ""
  form.openlist_user = data.storage?.openlist?.user || ""
  form.openlist_aria2_path = data.storage?.openlist?.aria2_path || ""
  form.openlist_target_path = data.storage?.openlist?.target_path || ""
  form.web_host = data.web?.host || ""
  form.web_port = data.web?.port || 3325
  form.telegram_bot_token = ""
  form.tmdb_token = ""
  form.aria2_token = ""
  form.sftp_password = ""
  form.openlist_password = ""
  form.web_token = ""
  secrets.telegram = Boolean(data.telegram_bot_token_set)
  secrets.tmdb = Boolean(data.tmdb_token_set)
  secrets.aria2 = Boolean(data.downloader?.aria2?.token_set)
  secrets.sftp = Boolean(data.storage?.sftp?.password_set)
  secrets.openlist = Boolean(data.storage?.openlist?.password_set)
  secrets.web = Boolean(data.web?.token_set)
  configPath.value = data.config_path || ""
}

async function save() {
  try {
    await api("/api/settings", {
      method: "PUT",
      body: {
        telegram_bot_token: form.telegram_bot_token,
        telegram_user_id: form.telegram_user_id,
        tmdb_token: form.tmdb_token,
        downloader: { aria2: { base_url: form.aria2_base_url, token: form.aria2_token } },
        storage: {
          provider: form.provider,
          folder_name_pattern: form.folder_name_pattern,
          video_name_pattern: form.video_name_pattern,
          local: { aria2_path: form.local_aria2_path, target_path: form.local_target_path },
          sftp: {
            host: form.sftp_host,
            port: form.sftp_port,
            user: form.sftp_user,
            password: form.sftp_password,
            pub_key: form.sftp_pub_key,
            aria2_path: form.sftp_aria2_path,
            target_path: form.sftp_target_path,
          },
          openlist: {
            base_url: form.openlist_base_url,
            user: form.openlist_user,
            password: form.openlist_password,
            aria2_path: form.openlist_aria2_path,
            target_path: form.openlist_target_path,
          },
        },
        web: { host: form.web_host, port: form.web_port, token: form.web_token },
      },
    })
    notify("配置已保存")
    await loadSettings()
  } catch (error) {
    notifyError(error)
  }
}

onMounted(() => {
  loadSettings().catch(notifyError)
})
</script>

<template>
  <form class="space-y-4" @submit.prevent="save">
    <h1 class="text-2xl font-semibold">
      配置
    </h1>
    <UCard>
      <template #header>
        <div>
          <h2 class="font-medium">
            账号与下载
          </h2>
          <p class="text-sm text-muted">
            还没填过的输入框里是填写示例。密钥留空表示不修改。
          </p>
        </div>
      </template>
      <div class="grid gap-4 md:grid-cols-2">
        <UFormField label="Telegram Bot Token">
          <UInput v-model="form.telegram_bot_token" class="w-full" :placeholder="secretPlaceholder(secrets.telegram, '向 @BotFather 申请，例如 123456:ABC')" type="password" />
        </UFormField>
        <UFormField label="Telegram 用户 ID">
          <UInput v-model="form.telegram_user_id" class="w-full" placeholder="你的数字 ID，可问 @userinfobot" />
        </UFormField>
        <UFormField label="TMDB Token">
          <UInput v-model="form.tmdb_token" class="w-full" :placeholder="secretPlaceholder(secrets.tmdb, 'TMDB 设置中的 API Read Access Token')" type="password" />
        </UFormField>
        <UFormField label="Aria2 地址">
          <UInput v-model="form.aria2_base_url" class="w-full" placeholder="http://127.0.0.1:6800/jsonrpc" />
        </UFormField>
        <UFormField label="Aria2 Token">
          <UInput v-model="form.aria2_token" class="w-full" :placeholder="secretPlaceholder(secrets.aria2, 'aria2.conf 里的 rpc-secret')" type="password" />
        </UFormField>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div>
          <h2 class="font-medium">
            命名
          </h2>
          <p class="text-sm text-muted">
            可用 &lt;filename&gt;、&lt;season&gt;、&lt;episode&gt;、&lt;ext&gt;。留空会使用框内提示的默认模板。
          </p>
        </div>
      </template>
      <div class="grid gap-4 md:grid-cols-2">
        <UFormField label="文件夹模板">
          <UInput v-model="form.folder_name_pattern" class="w-full" placeholder="<filename> (<first_air_date.year>)/Season <season>" />
        </UFormField>
        <UFormField label="文件名模板">
          <UInput v-model="form.video_name_pattern" class="w-full" placeholder="<filename> S<season:02d>E<episode:02d>.<ext>" />
        </UFormField>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <h2 class="font-medium">
          存储
        </h2>
      </template>
      <UFormField label="当前使用">
        <USelect v-model="form.provider" class="max-w-xs" :items="providerItems" />
      </UFormField>
      <p class="mt-2 text-sm text-muted">
        {{ providerHint }}
      </p>
      <div class="mt-4 space-y-4">
        <UCard :class="form.provider === 'local' ? '' : 'opacity-50'" variant="subtle">
          <template #header>
            <h3 class="font-medium">
              本地目录
            </h3>
            <p class="text-sm text-muted">
              Aria2 下完的目录，以及要整理进去的媒体库目录。
            </p>
          </template>
          <div class="grid gap-4 md:grid-cols-2">
            <UFormField label="下载目录">
              <UInput v-model="form.local_aria2_path" class="w-full" :disabled="form.provider !== 'local'" placeholder="/downloads" />
            </UFormField>
            <UFormField label="媒体库目录">
              <UInput v-model="form.local_target_path" class="w-full" :disabled="form.provider !== 'local'" placeholder="/anime" />
            </UFormField>
          </div>
        </UCard>
        <UCard :class="form.provider === 'sftp' ? '' : 'opacity-50'" variant="subtle">
          <template #header>
            <h3 class="font-medium">
              SFTP
            </h3>
            <p class="text-sm text-muted">
              密码和私钥填一个即可。目录是服务器上的路径。
            </p>
          </template>
          <div class="grid gap-4 md:grid-cols-2">
            <UFormField label="主机">
              <UInput v-model="form.sftp_host" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="192.168.1.10 或 example.com" />
            </UFormField>
            <UFormField label="端口">
              <UInput v-model.number="form.sftp_port" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="22" type="number" />
            </UFormField>
            <UFormField label="用户">
              <UInput v-model="form.sftp_user" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="登录用户名" />
            </UFormField>
            <UFormField label="密码">
              <UInput v-model="form.sftp_password" class="w-full" :disabled="form.provider !== 'sftp'" :placeholder="secretPlaceholder(secrets.sftp, '与私钥二选一')" type="password" />
            </UFormField>
            <UFormField label="私钥路径">
              <UInput v-model="form.sftp_pub_key" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="/home/you/.ssh/id_rsa" />
            </UFormField>
            <UFormField label="服务器下载目录">
              <UInput v-model="form.sftp_aria2_path" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="/data/aria2" />
            </UFormField>
            <UFormField label="服务器媒体库">
              <UInput v-model="form.sftp_target_path" class="w-full" :disabled="form.provider !== 'sftp'" placeholder="/data/anime" />
            </UFormField>
          </div>
        </UCard>
        <UCard :class="form.provider === 'openlist' ? '' : 'opacity-50'" variant="subtle">
          <template #header>
            <h3 class="font-medium">
              OpenList
            </h3>
            <p class="text-sm text-muted">
              地址一般是 OpenList 的网页地址。目录用网盘里的路径。
            </p>
          </template>
          <div class="grid gap-4 md:grid-cols-2">
            <UFormField label="地址">
              <UInput v-model="form.openlist_base_url" class="w-full" :disabled="form.provider !== 'openlist'" placeholder="http://127.0.0.1:5244" />
            </UFormField>
            <UFormField label="用户">
              <UInput v-model="form.openlist_user" class="w-full" :disabled="form.provider !== 'openlist'" placeholder="admin" />
            </UFormField>
            <UFormField label="密码">
              <UInput v-model="form.openlist_password" class="w-full" :disabled="form.provider !== 'openlist'" :placeholder="secretPlaceholder(secrets.openlist, '登录密码')" type="password" />
            </UFormField>
            <UFormField label="下载目录">
              <UInput v-model="form.openlist_aria2_path" class="w-full" :disabled="form.provider !== 'openlist'" placeholder="/aria2" />
            </UFormField>
            <UFormField label="媒体库目录">
              <UInput v-model="form.openlist_target_path" class="w-full" :disabled="form.provider !== 'openlist'" placeholder="/anime" />
            </UFormField>
          </div>
        </UCard>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div>
          <h2 class="font-medium">
            网页
          </h2>
          <p class="text-sm text-muted">
            只在这台电脑打开时用 127.0.0.1。Docker 里要给别人访问时改成 0.0.0.0，并设置令牌。
          </p>
        </div>
      </template>
      <div class="grid gap-4 md:grid-cols-2">
        <UFormField label="监听地址">
          <UInput v-model="form.web_host" class="w-full" placeholder="127.0.0.1" />
        </UFormField>
        <UFormField label="端口">
          <UInput v-model.number="form.web_port" class="w-full" placeholder="3325" type="number" />
        </UFormField>
        <UFormField label="访问令牌">
          <UInput v-model="form.web_token" class="w-full" :placeholder="secretPlaceholder(secrets.web, '留空则本机不校验')" type="password" />
        </UFormField>
      </div>
    </UCard>

    <div class="flex items-center gap-3">
      <UButton type="submit">
        保存配置
      </UButton>
      <p class="text-sm text-muted">
        当前文件：{{ configPath }}
      </p>
    </div>
  </form>
</template>
