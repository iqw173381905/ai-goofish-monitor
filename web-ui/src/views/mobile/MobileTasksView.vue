<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { Play, Square, RefreshCcw, Loader2, Pencil, X, BrainCircuit, Clock } from 'lucide-vue-next'
import { useTasks } from '@/composables/useTasks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toast'
import { formatCountdown, formatNextRunAbsolute } from '@/lib/taskSchedule'
import type { Task } from '@/types/task.d.ts'

const {
  tasks,
  isLoading,
  fetchTasks,
  startTask,
  stopTask,
  stoppingTaskIds,
  updateTask,
} = useTasks()

// cron 预设（和电脑端 TaskForm 一致）
const EMPTY_CRON_VALUE = '__manual__'
const cronPresets = computed(() => [
  { value: EMPTY_CRON_VALUE, label: '手动触发' },
  { value: '*/5 * * * *', label: '每 5 分钟' },
  { value: '*/15 * * * *', label: '每 15 分钟' },
  { value: '*/30 * * * *', label: '每 30 分钟' },
  { value: '0 * * * *', label: '每小时' },
  { value: '0 */2 * * *', label: '每 2 小时' },
  { value: '0 */6 * * *', label: '每 6 小时' },
  { value: '0 8 * * *', label: '每天 8 点' },
  { value: '0 12 * * *', label: '每天 12 点' },
  { value: '0 20 * * *', label: '每天 20 点' },
])
const isCustomCron = ref(false)

function isPresetCronValue(v: string) {
  if (!v) return true
  return cronPresets.value.some((p) => p.value === v)
}

// 编辑弹窗状态
const isEditOpen = ref(false)
const editingTask = ref<Task | null>(null)
const isSaving = ref(false)
const editForm = ref({
  task_name: '',
  keyword: '',
  description: '',
  min_price: '',
  max_price: '',
  max_pages: '',
  region: '',
  cron: '',
  personal_only: false,
  free_shipping: false,
  enabled: true,
})

// AI 标准重新生成
const isRegenerating = ref(false)

// 倒计时实时刷新（和电脑端一致：每秒更新）
const nowMs = ref(Date.now())
let countdownTimer: number | null = null

onMounted(() => {
  fetchTasks()
  countdownTimer = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (countdownTimer !== null) {
    window.clearInterval(countdownTimer)
    countdownTimer = null
  }
})

async function handleToggle(task: any) {
  try {
    if (task.is_running) {
      await stopTask(task.id)
    } else {
      await startTask(task.id)
    }
    await fetchTasks()
  } catch (e) {
    toast({
      title: '操作失败',
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
}

function isKeywordMode(task: any) {
  return task.decision_mode === 'keyword'
}

function openEdit(task: Task) {
  editingTask.value = task
  const cronVal = (task as any).cron || ''
  editForm.value = {
    task_name: task.task_name || '',
    keyword: task.keyword || '',
    description: (task as any).description || '',
    min_price: task.min_price != null ? String(task.min_price) : '',
    max_price: task.max_price != null ? String(task.max_price) : '',
    max_pages: (task as any).max_pages != null ? String((task as any).max_pages) : '',
    region: (task as any).region || '',
    cron: cronVal,
    personal_only: !!(task as any).personal_only,
    free_shipping: !!(task as any).free_shipping,
    enabled: !!task.enabled,
  }
  // 非预设的 cron 值 → 自定义模式
  isCustomCron.value = !!cronVal && !isPresetCronValue(cronVal)
  isEditOpen.value = true
}

function closeEdit() {
  isEditOpen.value = false
  editingTask.value = null
}

async function saveEdit() {
  if (!editingTask.value) return
  if (!editForm.value.task_name.trim()) {
    toast({ title: '任务名称不能为空', variant: 'destructive' })
    return
  }
  if (!editForm.value.keyword.trim()) {
    toast({ title: '关键词不能为空', variant: 'destructive' })
    return
  }
  isSaving.value = true
  try {
    await updateTask(editingTask.value.id, {
      task_name: editForm.value.task_name.trim(),
      keyword: editForm.value.keyword.trim(),
      description: editForm.value.description.trim(),
      min_price: editForm.value.min_price === '' ? null : Number(editForm.value.min_price),
      max_price: editForm.value.max_price === '' ? null : Number(editForm.value.max_price),
      max_pages: editForm.value.max_pages === '' ? null : Number(editForm.value.max_pages),
      region: editForm.value.region.trim() || null,
      cron: editForm.value.cron.trim() || null,
      personal_only: editForm.value.personal_only,
      free_shipping: editForm.value.free_shipping,
      enabled: editForm.value.enabled,
    } as any)
    toast({ title: '已保存' })
    closeEdit()
    await fetchTasks()
  } catch (e) {
    toast({
      title: '保存失败',
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isSaving.value = false
  }
}

// AI 标准重新生成
async function regenerateCriteria(task: Task) {
  if (isKeywordMode(task)) return
  isRegenerating.value = true
  try {
    await updateTask(task.id, {
      description: (task as any).description || task.task_name,
      regenerate_criteria: true,
    } as any)
    toast({ title: '已提交重新生成', description: 'AI 正在生成新的分析标准…' })
    await fetchTasks()
  } catch (e) {
    toast({
      title: '提交失败',
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isRegenerating.value = false
  }
}

function statusText(task: any) {
  if (task.is_running) return '运行中'
  if (!task.enabled) return '已禁用'
  return '待机'
}

function statusClass(task: any) {
  if (task.is_running) return 'bg-emerald-500'
  if (!task.enabled) return 'bg-slate-300'
  return 'bg-amber-400'
}

function scheduleText(task: any) {
  if (!task.cron) return '手动触发'
  const cd = formatCountdown(task.next_run_at, nowMs.value)
  if (cd) return `下次 ${cd}`
  const abs = formatNextRunAbsolute(task.next_run_at)
  return abs ? `下次 ${abs}` : task.cron
}
</script>

<template>
  <div class="p-4 space-y-3">
    <!-- 加载中 -->
    <div v-if="isLoading && tasks.length === 0" class="flex flex-col items-center justify-center py-16 gap-3 text-slate-400">
      <RefreshCcw class="w-8 h-8 animate-spin" />
      <p class="text-sm">加载任务中…</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-16 gap-3 text-slate-300">
      <p class="text-sm font-bold">暂无任务</p>
      <p class="text-xs">请在电脑端创建任务</p>
    </div>

    <!-- 任务卡片 -->
    <article
      v-for="task in tasks"
      :key="task.id"
      class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm"
    >
      <!-- 标题行 -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1.5">
            <h3 class="font-black text-slate-800 text-base truncate">{{ task.task_name }}</h3>
            <span
              v-if="!isKeywordMode(task)"
              class="text-[10px] font-black bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded flex-shrink-0"
            >
              AI
            </span>
          </div>
          <p class="text-xs text-slate-400 mt-0.5 truncate">{{ task.keyword }}</p>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <div class="flex items-center gap-1.5">
            <span :class="['w-2 h-2 rounded-full', statusClass(task), task.is_running && 'animate-pulse']"></span>
            <span class="text-xs font-bold text-slate-500">{{ statusText(task) }}</span>
          </div>
          <button
            type="button"
            class="w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-500 active:bg-slate-200"
            :aria-label="`编辑 ${task.task_name}`"
            @click="openEdit(task)"
          >
            <Pencil class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- 价格 + 定时 -->
      <div class="flex items-center gap-2 mt-2 text-xs text-slate-500 flex-wrap">
        <span class="font-bold">¥{{ task.min_price || 0 }} - {{ task.max_price || '不限' }}</span>
        <span v-if="(task as any).region" class="bg-slate-100 px-2 py-0.5 rounded-md">{{ (task as any).region }}</span>
        <span class="inline-flex items-center gap-1 bg-slate-50 px-2 py-0.5 rounded-md">
          <Clock class="w-3 h-3" /> {{ scheduleText(task) }}
        </span>
      </div>

      <!-- AI 标准生成中提示 -->
      <div
        v-if="!isKeywordMode(task) && (task as any).criteria_generating"
        class="mt-2 flex items-center gap-2 text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2"
      >
        <Loader2 class="w-3.5 h-3.5 animate-spin" />
        AI 分析标准生成中…
      </div>

      <!-- 操作按钮 -->
      <div class="mt-3 space-y-2">
        <Button
          v-if="!task.is_running"
          class="w-full h-12 text-base font-bold"
          :disabled="!task.enabled || stoppingTaskIds.has(task.id)"
          @click="handleToggle(task)"
        >
          <Play class="mr-2 h-5 w-5 fill-current" />
          启动任务
        </Button>
        <Button
          v-else
          variant="destructive"
          class="w-full h-12 text-base font-bold"
          :disabled="stoppingTaskIds.has(task.id)"
          @click="handleToggle(task)"
        >
          <Loader2 v-if="stoppingTaskIds.has(task.id)" class="mr-2 h-5 w-5 animate-spin" />
          <Square v-else class="mr-2 h-5 w-5 fill-current" />
          {{ stoppingTaskIds.has(task.id) ? '停止中…' : '停止任务' }}
        </Button>
        <!-- AI 标准重新生成 -->
        <Button
          v-if="!isKeywordMode(task) && !(task as any).criteria_generating"
          variant="outline"
          class="w-full h-10 text-sm"
          :disabled="isRegenerating"
          @click="regenerateCriteria(task)"
        >
          <BrainCircuit class="mr-2 h-4 w-4" />
          {{ isRegenerating ? '提交中…' : '重新生成 AI 标准' }}
        </Button>
      </div>
    </article>

    <p class="text-center text-xs text-slate-300 pt-2">
      创建任务请用电脑端
    </p>
  </div>

  <!-- 编辑弹窗 -->
  <div
    v-if="isEditOpen"
    class="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
    role="dialog"
    aria-modal="true"
  >
    <div class="absolute inset-0 bg-slate-950/40" @click="closeEdit"></div>
    <div class="relative w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl p-5 pb-8 max-h-[90vh] overflow-y-auto">
      <div class="flex items-center justify-between mb-4 sticky top-0 bg-white pb-2">
        <h2 class="text-base font-black text-slate-800">编辑任务</h2>
        <button
          type="button"
          class="w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-500"
          @click="closeEdit"
          aria-label="关闭"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="space-y-4">
        <div>
          <Label class="text-sm font-bold">任务名称</Label>
          <Input v-model="editForm.task_name" class="mt-1 h-12 text-base" placeholder="任务名称" />
        </div>
        <div>
          <Label class="text-sm font-bold">关键词</Label>
          <Input v-model="editForm.keyword" class="mt-1 h-12 text-base" placeholder="搜索关键词" />
        </div>
        <div>
          <Label class="text-sm font-bold">详细需求（AI 模式用）</Label>
          <Textarea v-model="editForm.description" class="mt-1 text-base min-h-[80px]" placeholder="描述你想要什么样的商品…" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <Label class="text-sm font-bold">最低价</Label>
            <Input v-model="editForm.min_price" type="number" inputmode="numeric" class="mt-1 h-12 text-base" placeholder="0" />
          </div>
          <div>
            <Label class="text-sm font-bold">最高价</Label>
            <Input v-model="editForm.max_price" type="number" inputmode="numeric" class="mt-1 h-12 text-base" placeholder="不限" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <Label class="text-sm font-bold">最大页数</Label>
            <Input v-model="editForm.max_pages" type="number" inputmode="numeric" class="mt-1 h-12 text-base" placeholder="默认" />
          </div>
          <div>
            <Label class="text-sm font-bold">地区</Label>
            <Input v-model="editForm.region" class="mt-1 h-12 text-base" placeholder="如：上海" />
          </div>
        </div>
        <div>
          <Label class="text-sm font-bold">定时任务</Label>
          <!-- 预设下拉 -->
          <select
            v-if="!isCustomCron"
            :value="editForm.cron || EMPTY_CRON_VALUE"
            @change="(e) => editForm.cron = (e.target as HTMLSelectElement).value === EMPTY_CRON_VALUE ? '' : (e.target as HTMLSelectElement).value"
            class="mt-1 w-full h-12 text-base rounded-xl border border-slate-200 bg-white px-3"
          >
            <option v-for="p in cronPresets" :key="p.value" :value="p.value">
              {{ p.label }}
            </option>
          </select>
          <!-- 自定义输入 -->
          <Input
            v-else
            v-model="editForm.cron"
            class="mt-1 h-12 text-base font-mono"
            placeholder="如：0 */2 * * *"
          />
          <button
            type="button"
            class="mt-1 text-xs text-primary font-bold"
            @click="isCustomCron = !isCustomCron"
          >
            {{ isCustomCron ? '← 使用预设' : '自定义 cron →' }}
          </button>
        </div>
        <div class="space-y-2">
          <div class="flex items-center justify-between py-1">
            <Label class="text-sm font-bold">只看个人卖家</Label>
            <Switch :model-value="editForm.personal_only" @update:model-value="(v: boolean) => editForm.personal_only = v" />
          </div>
          <div class="flex items-center justify-between py-1">
            <Label class="text-sm font-bold">只看包邮</Label>
            <Switch :model-value="editForm.free_shipping" @update:model-value="(v: boolean) => editForm.free_shipping = v" />
          </div>
          <div class="flex items-center justify-between py-1">
            <Label class="text-sm font-bold">启用任务</Label>
            <Switch :model-value="editForm.enabled" @update:model-value="(v: boolean) => editForm.enabled = v" />
          </div>
        </div>
      </div>

      <Button class="w-full h-12 mt-5 text-base font-bold" :disabled="isSaving" @click="saveEdit">
        <Loader2 v-if="isSaving" class="mr-2 h-5 w-5 animate-spin" />
        {{ isSaving ? '保存中…' : '保存' }}
      </Button>
      <!-- 底部安全区 -->
      <div class="h-[env(safe-area-inset-bottom)]"></div>
    </div>
  </div>
</template>
