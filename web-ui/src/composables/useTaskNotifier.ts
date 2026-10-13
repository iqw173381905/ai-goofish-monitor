// 全局推荐商品通知监听（App 挂载）
// 轮询任务列表，任务运行中实时检测新增推荐商品，立即弹出浏览器系统通知 + 页面 toast
import { onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from '@/components/ui/toast'
import { http } from '@/lib/http'
import type { Task } from '@/types/task.d.ts'

const STORAGE_KEY = 'monitor_browser_notify_enabled'
const POLL_INTERVAL_MS = 30000

export function isBrowserNotifyEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== '0'
  } catch {
    return true
  }
}

export function setBrowserNotifyEnabled(value: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    // ignore
  }
}

export function requestBrowserNotifyPermission() {
  if (!('Notification' in window)) return
  if (Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {})
  }
}

export function useTaskNotifier() {
  const { t } = useI18n()
  const prevRunning = new Map<number, boolean>()
  // 记录每个任务本轮开始运行的时间（ISO），用于只统计本轮新增的推荐
  const runStartAt = new Map<number, string>()
  // 记录每个任务本轮已通知过的推荐数量，避免重复弹窗
  const notifiedCount = new Map<number, number>()
  let timer: number | null = null
  let started = false

  function notifyRecommended(task: Task, newCount: number) {
    if (!isBrowserNotifyEnabled()) return
    if (newCount <= 0) return
    const title = t('notifyPanel.browser.taskDoneTitle')
    const body = t('notifyPanel.browser.taskDoneBody', { task: task.task_name, count: newCount })
    // 页面内 toast（当前页面任何位置都可见）
    toast({ title, description: body })
    // 浏览器系统弹窗
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        new Notification(title, { body, tag: `task-recommended-${task.id}-${Date.now()}` })
      } catch {
        // 某些环境构造失败时忽略
      }
    }
  }

  async function getRecommendedCountSince(taskId: number, since: string): Promise<number> {
    try {
      const res = (await http(
        `/api/tasks/${taskId}/recommended-since?since=${encodeURIComponent(since)}`
      )) as { count: number }
      return typeof res.count === 'number' ? res.count : 0
    } catch {
      // 查询失败时保守处理：不弹窗（避免误报），静默跳过
      return 0
    }
  }

  async function poll() {
    try {
      const list = (await http('/api/tasks')) as Task[]
      for (const task of list) {
        const wasRunning = prevRunning.get(task.id)
        const nowRunning = !!task.is_running
        if (wasRunning !== true && nowRunning === true) {
          // 任务刚开始运行：记录开始时间，重置已通知计数
          runStartAt.set(task.id, new Date().toISOString())
          notifiedCount.set(task.id, 0)
        }
        if (nowRunning === true) {
          // 任务运行中：实时检测本轮新增推荐，有新增立即弹窗（不等整轮结束）
          const since = runStartAt.get(task.id)
          if (since) {
            const total = await getRecommendedCountSince(task.id, since)
            const already = notifiedCount.get(task.id) ?? 0
            if (total > already) {
              notifyRecommended(task, total - already)
              notifiedCount.set(task.id, total)
            }
          }
        }
        if (wasRunning === true && nowRunning === false) {
          // 任务运行结束：清理本轮记录（推荐已在运行中实时通知过）
          runStartAt.delete(task.id)
          notifiedCount.delete(task.id)
        }
        prevRunning.set(task.id, nowRunning)
      }
      // 清理已删除任务的残留记录
      const aliveIds = new Set(list.map((t) => t.id))
      for (const id of [...prevRunning.keys()]) {
        if (!aliveIds.has(id)) {
          prevRunning.delete(id)
          runStartAt.delete(id)
          notifiedCount.delete(id)
        }
      }
    } catch {
      // 服务暂不可用则静默，下一轮再试
    }
  }

  onMounted(() => {
    if (started) return
    started = true
    requestBrowserNotifyPermission()
    poll()
    timer = window.setInterval(poll, POLL_INTERVAL_MS)
  })

  onUnmounted(() => {
    if (timer !== null) window.clearInterval(timer)
    timer = null
  })
}
