<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { RefreshCcw, ChevronDown, ArrowDown } from 'lucide-vue-next'
import { useTasks } from '@/composables/useTasks'
import { getLogs } from '@/api/logs'
import { toast } from '@/components/ui/toast'

const { tasks, fetchTasks } = useTasks()
const selectedTaskId = ref<number | null>(null)
const logs = ref('')
const pos = ref(0)
const isLoading = ref(false)
const autoRefresh = ref(true)
const logBox = ref<HTMLElement | null>(null)
let timer: number | null = null

async function loadLogs() {
  if (selectedTaskId.value === null || isLoading.value) return
  isLoading.value = true
  try {
    const data = await getLogs(pos.value, selectedTaskId.value)
    if (data.new_pos < pos.value) logs.value = ''
    if (data.new_content) {
      logs.value += data.new_content
      // 限制长度防止卡顿
      if (logs.value.length > 100_000) {
        logs.value = logs.value.slice(-80_000)
      }
    }
    pos.value = data.new_pos
    await nextTick()
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  } catch (e) {
    toast({ title: '加载失败', description: (e as Error).message, variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

function selectTask(id: number) {
  selectedTaskId.value = id
  logs.value = ''
  pos.value = 0
  loadLogs()
}

onMounted(async () => {
  await fetchTasks()
  if (tasks.value.length > 0) {
    selectTask(tasks.value[0]!.id)
  }
  timer = window.setInterval(() => {
    if (autoRefresh.value) loadLogs()
  }, 5000)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <div class="p-4 space-y-3 flex flex-col h-full">
    <!-- 任务选择 -->
    <div class="relative">
      <select
        :value="selectedTaskId ?? ''"
        @change="(e) => selectTask(Number((e.target as HTMLSelectElement).value))"
        class="w-full h-12 text-base rounded-xl border border-slate-200 bg-white px-3 pr-10 appearance-none font-bold"
      >
        <option value="" disabled>选择任务</option>
        <option v-for="t in tasks" :key="t.id" :value="t.id">
          {{ t.task_name }}
        </option>
      </select>
      <ChevronDown class="w-5 h-5 absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
    </div>

    <!-- 日志区域 -->
    <div class="flex items-center justify-between">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 text-xs font-bold"
        :class="autoRefresh ? 'text-primary' : 'text-slate-400'"
        @click="autoRefresh = !autoRefresh"
      >
        <span :class="['w-2 h-2 rounded-full', autoRefresh ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300']"></span>
        {{ autoRefresh ? '自动刷新开' : '自动刷新关' }}
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1 text-xs font-bold text-slate-500"
        @click="loadLogs"
      >
        <RefreshCcw class="w-4 h-4" :class="isLoading && 'animate-spin'" />
        刷新
      </button>
    </div>

    <div
      ref="logBox"
      class="flex-1 min-h-[50vh] bg-slate-900 rounded-2xl p-3 overflow-y-auto"
    >
      <pre v-if="logs" class="text-[11px] leading-relaxed text-slate-200 font-mono whitespace-pre-wrap break-words">{{ logs }}</pre>
      <p v-else class="text-xs text-slate-500 text-center py-8">
        {{ selectedTaskId === null ? '请先选择任务' : '暂无日志' }}
      </p>
    </div>
  </div>
</template>
