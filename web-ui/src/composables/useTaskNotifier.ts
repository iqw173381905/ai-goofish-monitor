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
  // 记录已通知过的商品 ID（持久化到 localStorage，页面刷新/多标签页也不会重复弹窗）
  // key: `notified_${taskId}`, value: JSON 数组
  const NOTIFIED_PREFIX = 'monitor_notified_items_'
  let timer: number | null = null
  let started = false

  function getNotifiedIds(taskId: number): Set<string> {
    try {
      const raw = localStorage.getItem(NOTIFIED_PREFIX + taskId)
      if (raw) return new Set(JSON.parse(raw) as string[])
    } catch { /* ignore */ }
    return new Set()
  }

  function addNotifiedIds(taskId: number, ids: string[]) {
    try {
      const set = getNotifiedIds(taskId)
      ids.forEach(id => set.add(id))
      // 只保留最近 500 个，防止无限增长
      const arr = [...set].slice(-500)
      localStorage.setItem(NOTIFIED_PREFIX + taskId, JSON.stringify(arr))
    } catch { /* ignore */ }
  }

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

  async function getRecommendedSince(taskId: number, since: string): Promise<{id: string, title: string}[]> {
    try {
      const res = (await http(
        `/api/tasks/${taskId}/recommended-since?since=${encodeURIComponent(since)}`
      )) as { items: {id: string, title: string}[] }
      return Array.isArray(res.items) ? res.items : []
    } catch {
      // 查询失败时保守处理：不弹窗（避免误报），静默跳过
      return []
    }
  }

  async function poll() {
    try {
      const list = (await http('/api/tasks')) as Task[]
      for (const task of list) {
        const wasRunning = prevRunning.get(task.id)
        const nowRunning = !!task.is_running
        if (wasRunning !== true && nowRunning === true) {
          // 任务刚开始运行：记录开始时间
          runStartAt.set(task.id, new Date().toISOString())
        }
        if (nowRunning === true) {
          // 任务运行中：实时检测本轮新增推荐，按商品 ID 去重后弹窗
          const since = runStartAt.get(task.id)
          if (since) {
            const items = await getRecommendedSince(task.id, since)
            const notified = getNotifiedIds(task.id)
            const fresh = items.filter(it => it.id && !notified.has(it.id))
            if (fresh.length > 0) {
              notifyRecommended(task, fresh.length)
              addNotifiedIds(task.id, fresh.map(it => it.id))
            }
          }
        }
        if (wasRunning === true && nowRunning === false) {
          // 任务运行结束：清理本轮开始时间（已通知 ID 保留在 localStorage 中防重复）
          runStartAt.delete(task.id)
        }
        prevRunning.set(task.id, nowRunning)
      }
      // 清理已删除任务的残留记录
      const aliveIds = new Set(list.map((t) => t.id))
      for (const id of [...prevRunning.keys()]) {
        if (!aliveIds.has(id)) {
          prevRunning.delete(id)
          runStartAt.delete(id)
          try { localStorage.removeItem(NOTIFIED_PREFIX + id) } catch { /* ignore */ }
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
