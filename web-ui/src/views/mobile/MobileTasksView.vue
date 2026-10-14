<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Play, Square, RefreshCcw, Loader2, Pencil, X } from 'lucide-vue-next'
import { useTasks } from '@/composables/useTasks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'
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

// 编辑弹窗状态
const isEditOpen = ref(false)
const editingTask = ref<Task | null>(null)
const isSaving = ref(false)
const editForm = ref({
  task_name: '',
  keyword: '',
  min_price: '',
  max_price: '',
  enabled: true,
})

onMounted(() => {
  fetchTasks()
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

function openEdit(task: Task) {
  editingTask.value = task
  editForm.value = {
    task_name: task.task_name || '',
    keyword: task.keyword || '',
    min_price: task.min_price != null ? String(task.min_price) : '',
    max_price: task.max_price != null ? String(task.max_price) : '',
    enabled: !!task.enabled,
  }
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
      min_price: editForm.value.min_price === '' ? null : Number(editForm.value.min_price),
      max_price: editForm.value.max_price === '' ? null : Number(editForm.value.max_price),
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
          <h3 class="font-black text-slate-800 text-base truncate">{{ task.task_name }}</h3>
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

      <!-- 价格区间 -->
      <div class="flex items-center gap-2 mt-2 text-xs text-slate-500">
        <span class="font-bold">¥{{ task.min_price || 0 }} - {{ task.max_price || '不限' }}</span>
        <span v-if="task.region" class="bg-slate-100 px-2 py-0.5 rounded-md">{{ task.region }}</span>
      </div>

      <!-- 操作按钮 -->
      <div class="mt-3">
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
    <div class="relative w-full max-w-lg bg-white rounded-t-3xl sm:rounded-3xl p-5 pb-8 max-h-[85vh] overflow-y-auto">
      <div class="flex items-center justify-between mb-4">
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
        <div class="flex items-center justify-between py-1">
          <Label class="text-sm font-bold">启用任务</Label>
          <Switch :model-value="editForm.enabled" @update:model-value="(v: boolean) => editForm.enabled = v" />
        </div>
      </div>

      <Button class="w-full h-12 mt-5 text-base font-bold" :disabled="isSaving" @click="saveEdit">
        <Loader2 v-if="isSaving" class="mr-2 h-5 w-5 animate-spin" />
        {{ isSaving ? '保存中…' : '保存' }}
      </Button>
    </div>
  </div>
</template>
