// 全局任务完成通知监听（App 挂载）
// 轮询任务列表，检测任务 running -> idle 转变，弹出浏览器系统通知 + 页面 toast
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
  let timer: number | null = null
  let started = false

  function notifyTaskDone(task: Task) {
    if (!isBrowserNotifyEnabled()) return
    const title = t('notifyPanel.browser.taskDoneTitle')
    const body = t('notifyPanel.browser.taskDoneBody', { task: task.task_name })
    // 页面内 toast（当前页面任何位置都可见）
    toast({ title, description: body })
    // 浏览器系统弹窗
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        new Notification(title, { body, tag: `task-done-${task.id}` })
      } catch {
        // 某些环境构造失败时忽略
      }
    }
  }

  async function poll() {
    try {
      const list = (await http('/api/tasks')) as Task[]
      for (const task of list) {
        const wasRunning = prevRunning.get(task.id)
        const nowRunning = !!task.is_running
        if (wasRunning === true && nowRunning === false) {
          notifyTaskDone(task)
        }
        prevRunning.set(task.id, nowRunning)
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
