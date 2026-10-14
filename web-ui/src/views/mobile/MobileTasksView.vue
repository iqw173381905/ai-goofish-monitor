<script setup lang="ts">
import { onMounted } from 'vue'
import { Play, Square, RefreshCcw, Loader2 } from 'lucide-vue-next'
import { useTasks } from '@/composables/useTasks'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'

const {
  tasks,
  isLoading,
  fetchTasks,
  startTask,
  stopTask,
  stoppingTaskIds,
} = useTasks()

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
        <div class="flex items-center gap-1.5 flex-shrink-0">
          <span :class="['w-2 h-2 rounded-full', statusClass(task), task.is_running && 'animate-pulse']"></span>
          <span class="text-xs font-bold text-slate-500">{{ statusText(task) }}</span>
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

    <!-- 底部提示 -->
    <p class="text-center text-xs text-slate-300 pt-2">
      创建/编辑任务请用电脑端
    </p>
  </div>
</template>
