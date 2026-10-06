<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useTasks } from '@/composables/useTasks'
import type { Task, TaskUpdate } from '@/types/task.d.ts'
import { parseTaskFormDefaults } from '@/lib/taskFormQuery'
import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import TasksTable from '@/components/tasks/TasksTable.vue'
import TaskForm from '@/components/tasks/TaskForm.vue'
import { listAccounts, type AccountItem } from '@/api/accounts'
import { getCriteriaContent, type CriteriaContent } from '@/api/tasks'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toast'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
const { t } = useI18n()

const {
  tasks,
  isLoading,
  error,
  fetchTasks,
  removeTask,
  updateTask,
  startTask,
  stopTask,
  stoppingTaskIds,
} = useTasks()
const route = useRoute()

// State for dialogs
const isEditDialogOpen = ref(false)
const isCriteriaDialogOpen = ref(false)
const isViewCriteriaOpen = ref(false)
const viewCriteriaTask = ref<Task | null>(null)
const criteriaContent = ref<CriteriaContent | null>(null)
const isCriteriaLoading = ref(false)
const isEditSubmitting = ref(false)
const selectedTask = ref<Task | null>(null)
const criteriaTask = ref<Task | null>(null)
const criteriaDescription = ref('')
const isCriteriaSubmitting = ref(false)
const isDeleteDialogOpen = ref(false)
const taskToDeleteId = ref<number | null>(null)
const accountOptions = ref<AccountItem[]>([])

const taskToDelete = computed(() => {
  if (taskToDeleteId.value === null) return null
  return tasks.value.find((task) => task.id === taskToDeleteId.value) || null
})
const editDefaults = computed(() => parseTaskFormDefaults(route.query))

function handleDeleteTask(taskId: number) {
  taskToDeleteId.value = taskId
  isDeleteDialogOpen.value = true
}

async function handleConfirmDeleteTask() {
  if (!taskToDelete.value) {
    toast({ title: t('tasks.toasts.notFound'), variant: 'destructive' })
    isDeleteDialogOpen.value = false
    return
  }
  try {
    await removeTask(taskToDelete.value.id)
    toast({ title: t('tasks.toasts.deleted') })
  } catch (e) {
    toast({
      title: t('tasks.toasts.deleteFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isDeleteDialogOpen.value = false
    taskToDeleteId.value = null
  }
}

function handleEditTask(task: Task) {
  selectedTask.value = task
  isEditDialogOpen.value = true
}

watch(
  () => [route.query.edit, tasks.value],
  () => {
    const editTaskId = typeof route.query.edit === 'string' ? Number(route.query.edit) : NaN
    if (!Number.isFinite(editTaskId)) return
    const match = tasks.value.find((task) => task.id === editTaskId)
    if (!match) return
    selectedTask.value = match
    isEditDialogOpen.value = true
  },
  { immediate: true }
)

async function handleUpdateTask(data: TaskUpdate) {
  if (!selectedTask.value) return
  isEditSubmitting.value = true
  try {
    await updateTask(selectedTask.value.id, data)
    isEditDialogOpen.value = false
  }
  catch (e) {
    toast({
      title: t('tasks.toasts.updateFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
  finally {
    isEditSubmitting.value = false
  }
}

function handleOpenCriteriaDialog(task: Task) {
  criteriaTask.value = task
  criteriaDescription.value = task.description || ''
  isCriteriaDialogOpen.value = true
}

async function handleViewCriteria(task: Task) {
  viewCriteriaTask.value = task
  isViewCriteriaOpen.value = true
  criteriaContent.value = null
  isCriteriaLoading.value = true
  try {
    criteriaContent.value = await getCriteriaContent(task.id)
  } catch (e) {
    toast({
      title: t('tasks.toasts.loadCriteriaFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isCriteriaLoading.value = false
  }
}

async function handleRefreshCriteria() {
  if (!criteriaTask.value) return
  if (!criteriaDescription.value.trim()) {
    toast({
      title: t('tasks.toasts.descriptionRequired'),
      description: t('tasks.criteria.descriptionRequired'),
      variant: 'destructive',
    })
    return
  }

  isCriteriaSubmitting.value = true
  try {
    // 强制重新生成：即使详细需求未变化也重新生成分析标准
    await updateTask(criteriaTask.value.id, {
      description: criteriaDescription.value,
      regenerate_criteria: true,
    })
    isCriteriaDialogOpen.value = false
    toast({
      title: t('tasks.toasts.regenerateSubmitted'),
      description: t('tasks.criteria.generatingHint'),
    })
    // 乐观置位：立即在列表显示"生成中"并禁用启动（后端在后台线程异步置位，
    // 不这样做列表要等下一次刷新才看到变化）
    const target = tasks.value.find((x) => x.id === criteriaTask.value!.id)
    if (target) {
      target.criteria_generating = true
      locallyGenerating.value.set(target.id, {
        baseline: target.criteria_generated_at ?? null,
        since: Date.now(),
      })
    }
    ensureCriteriaPolling()
  } catch (e) {
    toast({
      title: t('tasks.toasts.regenerateFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  } finally {
    isCriteriaSubmitting.value = false
  }
}

// AI 分析标准生成中：提交后立即显示"生成中"并轮询刷新，完成后 toast 提示
const criteriaPolling = ref<number | null>(null)
// 本地乐观标记：记录每个提交过重刷的任务 id → { 提交时 generated_at 基线, 提交时间戳 }
// 后端确认完成（generated_at 变化）前，即使轮询拉到 generating=false（后端未置位）也保持"生成中"
const locallyGenerating = ref<Map<number, { baseline: string | null; since: number }>>(new Map())
const criteriaDoneNotified = ref<Set<number>>(new Set())
// 提交后至少等待的秒数：避免"后端尚未置位"的竞态窗口被误判为失败
const CRITERIA_MIN_WAIT_MS = 15 * 1000
// 总超时：无论后端状态如何（含 fetchTasks 失败导致列表停在乐观置位的情况），
// 超过该时长一律判定失败，保证"生成中"永远不会无限期挂起
const CRITERIA_POLL_TIMEOUT_MS = 5 * 60 * 1000

function stopCriteriaPolling() {
  if (criteriaPolling.value !== null) {
    clearInterval(criteriaPolling.value)
    criteriaPolling.value = null
  }
}

async function criteriaPollOnce() {
  await fetchTasks({ silent: true })
  let anyPending = false
  const now = Date.now()
  for (const [id, entry] of [...locallyGenerating.value]) {
    const task = tasks.value.find((t) => t.id === id)
    if (!task) {
      locallyGenerating.value.delete(id)
      continue
    }
    // 无条件总超时兜底：即使列表数据因轮询失败而停留在"生成中"旧值，
    // 也会在超时后明确提示失败并结束，而不是永远转圈
    if (now - entry.since > CRITERIA_POLL_TIMEOUT_MS) {
      locallyGenerating.value.delete(id)
      // 强制解除本地"生成中"：后端 worker 可能已卡死（AI 中转无响应）无法清位，
      // 本地将其视为失败，徽标消失、启动按钮恢复可用
      const stuck = tasks.value.find((x) => x.id === id)
      if (stuck) stuck.criteria_generating = false
      if (!criteriaDoneNotified.value.has(id)) {
        criteriaDoneNotified.value.add(id)
        toast({
          title: t('tasks.toasts.regenerateFailed'),
          description: t('tasks.criteria.timeoutHint', { task: task.task_name }),
          variant: 'destructive',
        })
      }
      continue
    }
    if (task.criteria_generating) {
      anyPending = true
      continue
    }
    // 后端已清生成标记
    if (task.criteria_generated_at && task.criteria_generated_at !== entry.baseline) {
      // generated_at 相对提交时基线发生变化 → 确认生成完成
      locallyGenerating.value.delete(id)
      if (!criteriaDoneNotified.value.has(id)) {
        criteriaDoneNotified.value.add(id)
        toast({
          title: t('tasks.toasts.regenerateDone'),
          description: t('tasks.criteria.doneHint', { task: task.task_name }),
        })
      }
      continue
    }
    // 后端清位但 generated_at 未变：可能是提交后尚未置位的竞态窗口，
    // 超过最小等待后仍如此 → 判定为生成失败（AI 中转超时/出错）
    if (now - entry.since > CRITERIA_MIN_WAIT_MS) {
      locallyGenerating.value.delete(id)
      if (!criteriaDoneNotified.value.has(id)) {
        criteriaDoneNotified.value.add(id)
        toast({
          title: t('tasks.toasts.regenerateFailed'),
          description: t('tasks.criteria.failedHint', { task: task.task_name }),
          variant: 'destructive',
        })
      }
      continue
    }
    anyPending = true
  }
  if (!anyPending && locallyGenerating.value.size === 0) {
    stopCriteriaPolling()
  }
}

function ensureCriteriaPolling() {
  if (criteriaPolling.value === null) {
    criteriaPolling.value = window.setInterval(criteriaPollOnce, 3000)
    // 注意：不立即执行首次轮询。乐观置位刚写入本地任务对象，
    // 立即 fetchTasks 会用后端旧值（generating=false）覆盖，徽标瞬间消失。
    // 3 秒后首次轮询时后端 worker 必然已置位 generating=true。
  }
}

onUnmounted(stopCriteriaPolling)

async function handleStartTask(taskId: number) {
  try {
    await startTask(taskId)
  } catch (e) {
    toast({
      title: t('tasks.toasts.startFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
}

async function handleStopTask(taskId: number) {
  try {
    await stopTask(taskId)
  } catch (e) {
    toast({
      title: t('tasks.toasts.stopFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
}

async function handleToggleEnabled(task: Task, enabled: boolean) {
  const previous = task.enabled
  task.enabled = enabled
  try {
    await updateTask(task.id, { enabled })
  } catch (e) {
    task.enabled = previous
    toast({
      title: t('tasks.toasts.toggleFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
}

async function fetchAccountOptions() {
  try {
    accountOptions.value = await listAccounts()
  } catch (e) {
    toast({
      title: t('tasks.toasts.loadAccountsFailed'),
      description: (e as Error).message,
      variant: 'destructive',
    })
  }
}

onMounted(fetchAccountOptions)
</script>

<template>
  <div>
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold text-gray-800">
        {{ t('tasks.title') }}
      </h1>
      <TaskCreateDialog :account-options="accountOptions" @created="fetchTasks" />
    </div>

    <!-- Edit Task Dialog -->
    <Dialog v-model:open="isEditDialogOpen">
      <DialogContent class="sm:max-w-[640px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{{ t('tasks.editDialog.title', { task: selectedTask?.task_name || "" }) }}</DialogTitle>
        </DialogHeader>
        <TaskForm
          v-if="selectedTask"
          mode="edit"
          :initial-data="selectedTask"
          :account-options="accountOptions"
          :default-values="editDefaults"
          @submit="(data) => handleUpdateTask(data as TaskUpdate)"
        />
        <DialogFooter>
          <Button type="submit" form="task-form" :disabled="isEditSubmitting">
            {{ isEditSubmitting ? t('common.saving') : t('tasks.editDialog.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- View Criteria Content Dialog -->
    <Dialog v-model:open="isViewCriteriaOpen">
      <DialogContent class="sm:max-w-[720px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{{ t('tasks.criteria.viewTitle', { task: viewCriteriaTask?.task_name || "" }) }}</DialogTitle>
          <DialogDescription>
            {{ t('tasks.criteria.viewDescription') }}
          </DialogDescription>
        </DialogHeader>
        <div v-if="isCriteriaLoading" class="py-8 text-center text-sm text-gray-500">
          {{ t('tasks.criteria.loadingContent') }}
        </div>
        <div v-else-if="criteriaContent" class="grid gap-3">
          <div class="flex items-center gap-2 text-xs text-gray-500">
            <span class="font-medium">{{ t('tasks.criteria.currentFile') }}:</span>
            <span class="font-mono">{{ criteriaContent.filename || t('tasks.criteria.noFile') }}</span>
            <span v-if="criteriaContent.updated_at" class="ml-auto">
              {{ t('tasks.criteria.updatedAt') }}: {{ criteriaContent.updated_at.replace('T', ' ').slice(0, 19) }}
            </span>
          </div>
          <pre class="whitespace-pre-wrap break-words bg-slate-50 border border-slate-200 rounded-md p-3 text-[12px] leading-relaxed text-slate-700 max-h-[420px] overflow-y-auto">{{ criteriaContent.content || t('tasks.criteria.emptyContent') }}</pre>
        </div>
        <div v-else class="py-8 text-center text-sm text-gray-500">
          {{ t('tasks.criteria.emptyContent') }}
        </div>
        <DialogFooter>
          <Button variant="outline" @click="isViewCriteriaOpen = false">
            {{ t('common.close') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Refresh Criteria Dialog -->
    <Dialog v-model:open="isCriteriaDialogOpen">
      <DialogContent class="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{{ t('tasks.criteria.title') }}</DialogTitle>
          <DialogDescription>
            {{ t('tasks.criteria.description') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-3">
          <label class="text-sm font-medium text-gray-700">{{ t('tasks.form.description') }}</label>
          <Textarea
            v-model="criteriaDescription"
            class="min-h-[140px]"
            :placeholder="t('tasks.form.descriptionPlaceholder')"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="isCriteriaDialogOpen = false">
            {{ t('common.cancel') }}
          </Button>
          <Button :disabled="isCriteriaSubmitting" @click="handleRefreshCriteria">
            {{ isCriteriaSubmitting ? t('tasks.criteria.generating') : t('tasks.criteria.action') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <div v-if="error" class="app-alert-error mb-4" role="alert">
      <strong class="font-bold">{{ t('common.error') }}</strong>
      <span class="block sm:inline">{{ error.message }}</span>
    </div>

    <TasksTable
      :tasks="tasks"
      :is-loading="isLoading"
      :stopping-ids="stoppingTaskIds"
      @delete-task="handleDeleteTask"
      @edit-task="handleEditTask"
      @run-task="handleStartTask"
      @stop-task="handleStopTask"
      @refresh-criteria="handleOpenCriteriaDialog"
      @view-criteria="handleViewCriteria"
      @toggle-enabled="handleToggleEnabled"
    />

    <Dialog v-model:open="isDeleteDialogOpen">
      <DialogContent class="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>{{ t('tasks.deleteDialog.title') }}</DialogTitle>
          <DialogDescription>
            {{ taskToDelete ? t('tasks.deleteDialog.descriptionWithTask', { task: taskToDelete.task_name }) : t('tasks.deleteDialog.descriptionFallback') }}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="isDeleteDialogOpen = false">{{ t('common.cancel') }}</Button>
          <Button variant="destructive" @click="handleConfirmDeleteTask">{{ t('tasks.deleteDialog.confirm') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
