<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { Play, Square, RefreshCcw, Loader2, Pencil, X, BrainCircuit, Clock, Plus, Pause } from 'lucide-vue-next'
import { useTasks } from '@/composables/useTasks'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { formatCountdown, formatNextRunAbsolute } from '@/lib/taskSchedule'
import TaskForm from '@/components/tasks/TaskForm.vue'
import { listAccounts, type AccountItem } from '@/api/accounts'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import type { Task, TaskUpdate } from '@/types/task.d.ts'

const {
  tasks,
  isLoading,
  fetchTasks,
  startTask,
  stopTask,
  stoppingTaskIds,
  updateTask,
  createTask,
} = useTasks()

// 编辑弹窗状态（直接复用电脑端 TaskForm，保证功能 100% 一致）
const isEditOpen = ref(false)
const editingTask = ref<Task | null>(null)
const isSaving = ref(false)
const accountOptions = ref<AccountItem[]>([])

// 新建任务弹窗（复用电脑端 TaskForm create 模式）
const isCreateOpen = ref(false)
const isCreating = ref(false)
function openCreate() {
  isCreateOpen.value = true
}
function closeCreate() {
  isCreateOpen.value = false
}
async function handleCreateTask(data: any) {
  isCreating.value = true
  try {
    await createTask(data)
    toast({ title: '任务已创建' })
    closeCreate()
    await fetchTasks()
  } catch (e) {
    toast({
      title: '创建失败',
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isCreating.value = false
  }
}

// AI 标准重新生成
const isRegenerating = ref(false)

// 倒计时实时刷新（和电脑端一致：每秒更新）
const nowMs = ref(Date.now())
let countdownTimer: number | null = null

onMounted(async () => {
  fetchTasks()
  countdownTimer = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
  try {
    accountOptions.value = await listAccounts()
  } catch { /* 账号列表加载失败不阻塞 */ }
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

async function handleToggleSchedulePaused(task: any) {
  const paused = !task.schedule_paused
  const previous = task.schedule_paused
  task.schedule_paused = paused
  try {
    await updateTask(task.id, { schedule_paused: paused })
    toast({ title: paused ? '定时已暂停' : '定时已恢复' })
    await fetchTasks()
  } catch (e) {
    task.schedule_paused = previous
    toast({
      title: '暂停/恢复定时失败',
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
  isEditOpen.value = true
}

function closeEdit() {
  isEditOpen.value = false
  editingTask.value = null
}

async function handleUpdateTask(data: TaskUpdate) {
  if (!editingTask.value) return
  isSaving.value = true
  try {
    await updateTask(editingTask.value.id, data)
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
const isCriteriaOpen = ref(false)
const criteriaTask = ref<Task | null>(null)
const criteriaDescription = ref('')

function openCriteriaDialog(task: Task) {
  criteriaTask.value = task
  criteriaDescription.value = (task as any).description || ''
  isCriteriaOpen.value = true
}

function closeCriteriaDialog() {
  isCriteriaOpen.value = false
  criteriaTask.value = null
}

// AI 标准重新生成（弹窗编辑提示词后提交）
async function submitCriteria() {
  if (!criteriaTask.value) return
  if (!criteriaDescription.value.trim()) {
    toast({ title: '请填写需求描述', variant: 'destructive' })
    return
  }
  isRegenerating.value = true
  try {
    await updateTask(criteriaTask.value.id, {
      description: criteriaDescription.value.trim(),
      regenerate_criteria: true,
    } as any)
    toast({ title: '已提交重新生成', description: 'AI 正在生成新的分析标准…' })
    closeCriteriaDialog()
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
  if (task.schedule_paused) return '定时暂停'
  return '待机'
}

function statusClass(task: any) {
  if (task.is_running) return 'bg-emerald-500'
  if (!task.enabled) return 'bg-slate-300'
  return 'bg-amber-400'
}

function scheduleText(task: any) {
  if (!task.cron) return '手动触发'
  if (task.schedule_paused) return '定时已暂停'
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
      <Button class="mt-2 h-11 px-6 text-base font-bold" @click="openCreate">
        <Plus class="mr-2 h-5 w-5" />
        新建任务
      </Button>
    </div>

    <!-- 新建任务按钮 -->
    <Button
      v-else
      class="w-full h-12 text-base font-bold"
      @click="openCreate"
    >
      <Plus class="mr-2 h-5 w-5" />
      新建任务
    </Button>

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
        <!-- 暂停 / 恢复定时 -->
        <Button
          v-if="task.cron"
          variant="outline"
          class="w-full h-10 text-sm"
          :class="task.schedule_paused ? 'text-emerald-700 border-emerald-200' : 'text-amber-700 border-amber-200'"
          @click="handleToggleSchedulePaused(task)"
        >
          <Play v-if="task.schedule_paused" class="mr-2 h-4 w-4 fill-current" />
          <Pause v-else class="mr-2 h-4 w-4 fill-current" />
          {{ task.schedule_paused ? '恢复定时' : '暂停定时' }}
        </Button>
        <!-- AI 标准重新生成 -->
        <Button
          v-if="!isKeywordMode(task) && !(task as any).criteria_generating"
          variant="outline"
          class="w-full h-10 text-sm"
          @click="openCriteriaDialog(task)"
        >
          <BrainCircuit class="mr-2 h-4 w-4" />
          重新生成 AI 标准
        </Button>
      </div>
    </article>

  </div>

  <!-- 编辑弹窗：直接复用电脑端 TaskForm -->
  <div
    v-if="isEditOpen"
    class="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
    role="dialog"
    aria-modal="true"
  >
    <div class="absolute inset-0 bg-slate-950/40" @click="closeEdit"></div>
    <div class="relative w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl max-h-[92vh] flex flex-col overflow-hidden">
      <div class="flex items-center justify-between p-5 pb-3 flex-shrink-0">
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
      <div class="flex-1 overflow-y-auto px-5">
        <TaskForm
          v-if="editingTask"
          mode="edit"
          :initial-data="editingTask"
          :account-options="accountOptions"
          @submit="(data) => handleUpdateTask(data as TaskUpdate)"
        />
      </div>
      <div class="p-5 pt-3 flex-shrink-0 border-t border-slate-100">
        <Button
          type="submit"
          form="task-form"
          class="w-full h-12 text-base font-bold"
          :disabled="isSaving"
        >
          <Loader2 v-if="isSaving" class="mr-2 h-5 w-5 animate-spin" />
          {{ isSaving ? '保存中…' : '保存' }}
        </Button>
        <div class="h-[env(safe-area-inset-bottom)]"></div>
      </div>
    </div>
  </div>
  <!-- 新建任务弹窗：复用电脑端 TaskForm -->
  <div
    v-if="isCreateOpen"
    class="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
    role="dialog"
    aria-modal="true"
  >
    <div class="absolute inset-0 bg-slate-950/40" @click="closeCreate"></div>
    <div class="relative w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl max-h-[92vh] flex flex-col overflow-hidden">
      <div class="flex items-center justify-between p-5 pb-3 flex-shrink-0">
        <h2 class="text-base font-black text-slate-800">新建任务</h2>
        <button
          type="button"
          class="w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-500"
          @click="closeCreate"
          aria-label="关闭"
        >
          <X class="w-5 h-5" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto px-5">
        <TaskForm
          mode="create"
          :account-options="accountOptions"
          @submit="(data) => handleCreateTask(data)"
        />
      </div>
      <div class="p-5 pt-3 flex-shrink-0 border-t border-slate-100">
        <Button
          type="submit"
          form="task-form"
          class="w-full h-12 text-base font-bold"
          :disabled="isCreating"
        >
          <Loader2 v-if="isCreating" class="mr-2 h-5 w-5 animate-spin" />
          {{ isCreating ? '创建中…' : '创建任务' }}
        </Button>
        <div class="h-[env(safe-area-inset-bottom)]"></div>
      </div>
    </div>
  </div>

  <!-- AI 标准编辑弹窗 -->
  <div
    v-if="isCriteriaOpen"
    class="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
    role="dialog"
    aria-modal="true"
  >
    <div class="absolute inset-0 bg-slate-950/40" @click="closeCriteriaDialog"></div>
    <div class="relative w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl p-5 pb-8 max-h-[85vh] overflow-y-auto">
      <div class="flex items-center justify-between mb-2">
        <h2 class="text-base font-black text-slate-800">重新生成 AI 标准</h2>
        <button
          type="button"
          class="w-9 h-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-500"
          @click="closeCriteriaDialog"
          aria-label="关闭"
        >
          <X class="w-5 h-5" />
        </button>
      </div>
      <p class="text-xs text-slate-400 mb-3">
        修改需求描述后提交，AI 会重新生成分析标准
      </p>
      <div>
        <Label class="text-sm font-bold">需求描述</Label>
        <Textarea
          v-model="criteriaDescription"
          class="mt-1 min-h-[140px] text-base"
          placeholder="描述你想要什么样的商品…"
        />
      </div>
      <div class="flex gap-2 mt-4">
        <Button variant="outline" class="flex-1 h-12 text-base" @click="closeCriteriaDialog">
          取消
        </Button>
        <Button class="flex-1 h-12 text-base font-bold" :disabled="isRegenerating" @click="submitCriteria">
          <Loader2 v-if="isRegenerating" class="mr-2 h-5 w-5 animate-spin" />
          {{ isRegenerating ? '生成中…' : '提交生成' }}
        </Button>
      </div>
      <div class="h-[env(safe-area-inset-bottom)]"></div>
    </div>
  </div>
</template>
