<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { RefreshCcw, Bell, BrainCircuit, Server, TestTube2, Check } from 'lucide-vue-next'
import { useSettings } from '@/composables/useSettings'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'
import { getAiProfiles, applyAiProfile } from '@/api/settings'

const {
  notificationSettings,
  aiSettings,
  systemStatus,
  isReady,
  fetchAll,
  refreshStatus,
  saveNotificationSettings,
  testNotification,
} = useSettings()

onMounted(fetchAll)

const runningTaskCount = computed(() => systemStatus.value?.running_task_ids?.length ?? 0)
const configuredChannels = computed<string[]>(
  () => (notificationSettings.value as any).CONFIGURED_CHANNELS ?? []
)

const channelLabels: Record<string, string> = {
  ntfy: 'Ntfy',
  pushplus: 'PushPlus',
  gotify: 'Gotify',
  bark: 'Bark',
  wx_bot: '企业微信',
  telegram: 'Telegram',
  webhook: 'Webhook',
}

const isTesting = ref(false)

// AI 模型切换
interface AiProfileItem {
  id: number
  name: string
  model: string
  enabled: boolean
  priority: number
}
const aiProfiles = ref<AiProfileItem[]>([])
const activeProfileId = ref<number | null>(null)
const switchingProfile = ref(false)

async function loadAiProfiles() {
  try {
    const res: any = await getAiProfiles()
    const list: AiProfileItem[] = res.profiles ?? res ?? []
    aiProfiles.value = list
      .filter(p => p.enabled)
      .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || a.id - b.id)
    // 优先级最高的即为当前生效
    activeProfileId.value = aiProfiles.value.length ? aiProfiles.value[0]!.id : null
  } catch (e) {
    console.warn('加载 AI 模型列表失败', e)
  }
}

async function switchAiProfile(profile: AiProfileItem) {
  if (switchingProfile.value || profile.id === activeProfileId.value) return
  switchingProfile.value = true
  try {
    await applyAiProfile(profile.id)
    activeProfileId.value = profile.id
    toast({ title: `已切换到 ${profile.name}` })
    await fetchAll()
  } catch (e) {
    toast({ title: '切换失败', description: (e as Error).message, variant: 'destructive' })
  } finally {
    switchingProfile.value = false
  }
}

onMounted(() => {
  loadAiProfiles()
})

async function togglePcurl(value: boolean) {
  try {
    await saveNotificationSettings({ PCURL_TO_MOBILE: value })
    toast({ title: value ? '通知链接已优先使用手机版' : '通知链接已恢复电脑版' })
  } catch (e) {
    toast({ title: '保存失败', description: (e as Error).message, variant: 'destructive' })
    await fetchAll()
  }
}

async function handleTest() {
  if (!configuredChannels.value.length) {
    toast({ title: '没有已配置的通知渠道', description: '请先在电脑端配置通知渠道', variant: 'destructive' })
    return
  }
  isTesting.value = true
  try {
    const res = await testNotification({ settings: {} })
    const failed = Object.entries(res.results).filter(([, r]) => !r.success)
    if (!failed.length) {
      toast({ title: '测试通知已发送' })
    } else {
      toast({
        title: '部分渠道测试失败',
        description: failed.map(([k, r]) => `${channelLabels[k] ?? k}：${r.message}`).join('\n'),
        variant: 'destructive',
      })
    }
  } catch (e) {
    toast({ title: '测试失败', description: (e as Error).message, variant: 'destructive' })
  } finally {
    isTesting.value = false
  }
}
</script>

<template>
  <div class="p-4 space-y-4">
    <div v-if="!isReady" class="flex flex-col items-center py-16 gap-3 text-slate-400">
      <RefreshCcw class="w-8 h-8 animate-spin" />
      <p class="text-sm">加载设置中…</p>
    </div>

    <template v-else>
      <!-- 系统状态 -->
      <section class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-black text-slate-800 inline-flex items-center gap-2">
            <Server class="w-4 h-4 text-primary" /> 系统状态
          </h2>
          <button
            type="button"
            class="text-xs font-bold text-primary"
            @click="refreshStatus"
          >
            刷新
          </button>
        </div>
        <div v-if="systemStatus" class="space-y-1.5 text-xs text-slate-500">
          <div class="flex justify-between">
            <span>爬虫</span>
            <span class="font-bold" :class="systemStatus.scraper_running ? 'text-emerald-600' : 'text-slate-400'">
              {{ systemStatus.scraper_running ? '运行中' : '空闲' }}
            </span>
          </div>
          <div class="flex justify-between">
            <span>运行中任务</span>
            <span class="font-bold text-slate-700">{{ runningTaskCount }}</span>
          </div>
          <div class="flex justify-between">
            <span>AI 配置</span>
            <span class="font-bold" :class="systemStatus.ai_configured ? 'text-emerald-600' : 'text-slate-400'">
              {{ systemStatus.ai_configured ? '已配置' : '未配置' }}
            </span>
          </div>
          <div class="flex justify-between">
            <span>通知配置</span>
            <span class="font-bold" :class="systemStatus.notification_configured ? 'text-emerald-600' : 'text-slate-400'">
              {{ systemStatus.notification_configured ? '已配置' : '未配置' }}
            </span>
          </div>
        </div>
      </section>

      <!-- 通知设置 -->
      <section class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm">
        <h2 class="text-sm font-black text-slate-800 inline-flex items-center gap-2 mb-3">
          <Bell class="w-4 h-4 text-primary" /> 通知
        </h2>
        <div class="space-y-3">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm text-slate-600">已配置渠道</span>
            <span v-if="configuredChannels.length" class="text-xs font-bold text-slate-700 text-right">
              {{ configuredChannels.map((c) => channelLabels[c] ?? c).join('、') }}
            </span>
            <span v-else class="text-xs text-slate-400">未配置</span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm text-slate-600">链接优先手机版</span>
            <Switch
              :model-value="!!(notificationSettings as any).PCURL_TO_MOBILE"
              @update:model-value="(v) => togglePcurl(!!v)"
            />
          </div>
          <button
            type="button"
            :disabled="isTesting"
            class="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 py-2.5 text-sm font-bold text-slate-700 active:bg-slate-100 disabled:opacity-50"
            @click="handleTest"
          >
            <TestTube2 class="w-4 h-4" />
            {{ isTesting ? '发送中…' : '发送测试通知' }}
          </button>
        </div>
        <p class="text-xs text-slate-300 mt-3">增删通知渠道请在电脑端配置</p>
      </section>

      <!-- AI 设置 -->
      <section class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm">
        <h2 class="text-sm font-black text-slate-800 inline-flex items-center gap-2 mb-3">
          <BrainCircuit class="w-4 h-4 text-primary" /> AI
        </h2>
        <!-- 模型切换 -->
        <div v-if="aiProfiles.length" class="mb-3">
          <p class="text-xs text-slate-400 mb-2">当前生效模型（点击切换）</p>
          <div class="space-y-1.5">
            <button
              v-for="p in aiProfiles"
              :key="p.id"
              @click="switchAiProfile(p)"
              :disabled="switchingProfile"
              class="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl border text-xs transition active:scale-[0.98]"
              :class="p.id === activeProfileId
                ? 'border-primary bg-primary/5 text-slate-800 font-bold'
                : 'border-slate-200 text-slate-600'"
            >
              <span class="truncate">{{ p.name }} <span class="text-slate-400 font-normal">({{ p.model }})</span></span>
              <Check v-if="p.id === activeProfileId" class="w-4 h-4 text-primary shrink-0" />
            </button>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-500">
          <div class="flex justify-between gap-2">
            <span class="shrink-0">模型</span>
            <span class="font-bold text-slate-700 font-mono text-right break-all">{{ (aiSettings as any).OPENAI_MODEL_NAME || '-' }}</span>
          </div>
          <div class="flex justify-between gap-2">
            <span class="shrink-0">接口地址</span>
            <span class="font-bold text-slate-700 font-mono text-right break-all">{{ (aiSettings as any).OPENAI_BASE_URL || '-' }}</span>
          </div>
        </div>
        <p class="text-xs text-slate-300 mt-3">修改其他 AI 参数请在电脑端配置</p>
      </section>
    </template>
  </div>
</template>
