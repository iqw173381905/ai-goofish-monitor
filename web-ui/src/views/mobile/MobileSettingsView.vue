<script setup lang="ts">
import { onMounted } from 'vue'
import { RefreshCcw, Bell, BrainCircuit, Server } from 'lucide-vue-next'
import { useSettings } from '@/composables/useSettings'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'

const {
  notificationSettings,
  aiSettings,
  systemStatus,
  isReady,
  fetchAll,
  refreshStatus,
  saveNotificationSettings,
} = useSettings()

onMounted(fetchAll)

async function toggleNotify(key: string, value: boolean) {
  try {
    await saveNotificationSettings({ [key]: value } as any)
  } catch (e) {
    toast({ title: '保存失败', description: (e as Error).message, variant: 'destructive' })
    await fetchAll()
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
            <span>任务数</span>
            <span class="font-bold text-slate-700">{{ (systemStatus as any).task_count ?? '-' }}</span>
          </div>
          <div class="flex justify-between">
            <span>运行中</span>
            <span class="font-bold text-slate-700">{{ (systemStatus as any).running_count ?? '-' }}</span>
          </div>
        </div>
      </section>

      <!-- 通知设置 -->
      <section class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm">
        <h2 class="text-sm font-black text-slate-800 inline-flex items-center gap-2 mb-3">
          <Bell class="w-4 h-4 text-primary" /> 通知
        </h2>
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-sm text-slate-600">启用通知</span>
            <Switch
              :model-value="!!(notificationSettings as any).enabled"
              @update:model-value="(v) => toggleNotify('enabled', v)"
            />
          </div>
        </div>
        <p class="text-xs text-slate-300 mt-3">详细通知渠道请在电脑端配置</p>
      </section>

      <!-- AI 设置 -->
      <section class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm">
        <h2 class="text-sm font-black text-slate-800 inline-flex items-center gap-2 mb-3">
          <BrainCircuit class="w-4 h-4 text-primary" /> AI
        </h2>
        <div class="space-y-1.5 text-xs text-slate-500">
          <div class="flex justify-between">
            <span>模型</span>
            <span class="font-bold text-slate-700 font-mono">{{ (aiSettings as any).model || '-' }}</span>
          </div>
        </div>
        <p class="text-xs text-slate-300 mt-3">AI 参数请在电脑端配置</p>
      </section>
    </template>
  </div>
</template>
