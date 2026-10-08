<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  dateFrom: string
  dateTo: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:dateFrom', value: string): void
  (e: 'update:dateTo', value: string): void
}>()

const { t } = useI18n()

const open = ref(false)
const viewYear = ref<number>(new Date().getFullYear())
const viewMonth = ref<number>(new Date().getMonth()) // 0-11

// 面板内临时选择（点击日历天时更新，确认时统一提交）
const tempStart = ref<string>('')
const tempEnd = ref<string>('')

const WEEK_START = 1 // 周一为每周第一天

function fmtDate(year: number, month: number, day: number): string {
  const y = String(year)
  const m = String(month + 1).padStart(2, '0')
  const d = String(day).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function todayStr(): string {
  const now = new Date()
  return fmtDate(now.getFullYear(), now.getMonth(), now.getDate())
}

function initViewFromSelection() {
  const base = props.dateFrom || props.dateTo || todayStr()
  const parts = base.split('-')
  if (parts.length === 3) {
    viewYear.value = Number(parts[0])
    viewMonth.value = Number(parts[1]) - 1
  }
}

function openPanel() {
  tempStart.value = props.dateFrom || ''
  tempEnd.value = props.dateTo || ''
  initViewFromSelection()
  open.value = true
}

function closePanel() {
  open.value = false
}

function togglePanel() {
  if (open.value) closePanel()
  else openPanel()
}

function clearRange() {
  tempStart.value = ''
  tempEnd.value = ''
  emit('update:dateFrom', '')
  emit('update:dateTo', '')
}

// 当月网格：从周一开头
const grid = computed(() => {
  const year = viewYear.value
  const month = viewMonth.value
  const firstWeekday = new Date(year, month, 1).getDay() // 0=周日
  let leading = (firstWeekday - WEEK_START + 7) % 7
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (string | null)[] = []
  for (let i = 0; i < leading; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(fmtDate(year, month, d))
  // 补齐到整行
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
})

const weekLabels = computed(() => ['一', '二', '三', '四', '五', '六', '日'])

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`)

function prevMonth() {
  viewMonth.value -= 1
  if (viewMonth.value < 0) {
    viewMonth.value = 11
    viewYear.value -= 1
  }
}

function nextMonth() {
  viewMonth.value += 1
  if (viewMonth.value > 11) {
    viewMonth.value = 0
    viewYear.value += 1
  }
}

function inRange(day: string): boolean {
  if (!tempStart.value || !tempEnd.value) return false
  return day >= tempStart.value && day <= tempEnd.value
}

function isStart(day: string): boolean {
  return tempStart.value === day
}

function isEnd(day: string): boolean {
  return tempEnd.value === day
}

function pickDay(day: string) {
  if (!tempStart.value) {
    tempStart.value = day
    tempEnd.value = ''
    return
  }
  if (!tempEnd.value) {
    if (day < tempStart.value) {
      // 比开始早：重新设为开始
      tempStart.value = day
    } else if (day === tempStart.value) {
      // 同一天：单日区间
      tempEnd.value = day
    } else {
      tempEnd.value = day
    }
    // 有开始有结束：立即提交
    emit('update:dateFrom', tempStart.value)
    emit('update:dateTo', tempEnd.value)
    closePanel()
    return
  }
  // 已完整选择：再次点击开始新一轮
  tempStart.value = day
  tempEnd.value = ''
}

function onDocumentClick() {
  if (open.value) closePanel()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

watch(open, (val) => {
  if (val) {
    initViewFromSelection()
  }
})

const displayText = computed(() => {
  if (props.dateFrom && props.dateTo) {
    return `${props.dateFrom} — ${props.dateTo}`
  }
  if (props.dateFrom) {
    return t('results.filters.dateRangeOpenEnd', { from: props.dateFrom })
  }
  return t('results.filters.dateRangeAll')
})
</script>

<template>
  <div class="relative" @click.stop>
    <button
      type="button"
      class="flex h-9 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
      @click="togglePanel"
    >
      <svg class="h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="4" width="18" height="17" rx="2" />
        <path d="M8 2v4M16 2v4M3 10h18" />
      </svg>
      <span class="whitespace-nowrap">{{ displayText }}</span>
      <span v-if="dateFrom || dateTo" class="ml-1 cursor-pointer text-slate-400 hover:text-slate-600" title="清除日期筛选" @click.stop="clearRange">✕</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 top-full z-50 mt-1 w-[300px] rounded-lg border border-slate-200 bg-white p-3 shadow-lg"
    >
      <div class="mb-2 flex items-center justify-between">
        <button type="button" class="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100" @click="prevMonth">‹</button>
        <span class="text-sm font-semibold text-slate-700">{{ monthLabel }}</span>
        <button type="button" class="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100" @click="nextMonth">›</button>
      </div>

      <div class="mb-1 grid grid-cols-7 text-center text-xs font-medium text-slate-400">
        <span v-for="w in weekLabels" :key="w" class="py-1">{{ w }}</span>
      </div>

      <div class="grid grid-cols-7 gap-y-1 text-center">
        <template v-for="(cell, idx) in grid" :key="idx">
          <span v-if="!cell" class="py-1"></span>
          <button
            v-else
            type="button"
            class="relative mx-auto flex h-8 w-8 items-center justify-center"
            @click="pickDay(cell)"
          >
            <span
              v-if="inRange(cell) && !isStart(cell) && !isEnd(cell)"
              class="absolute inset-y-0 -left-1 -right-1 bg-blue-100"
            ></span>
            <span
              :class="[
                'relative z-10 flex h-8 w-8 items-center justify-center rounded-full',
                isStart(cell) || isEnd(cell)
                  ? 'bg-blue-600 text-white font-semibold'
                  : inRange(cell)
                    ? 'text-blue-700'
                    : cell === todayStr()
                      ? 'text-blue-600 font-semibold'
                      : 'text-slate-700 hover:bg-slate-100',
              ]"
            >
              {{ Number(cell.slice(-2)) }}
            </span>
          </button>
        </template>
      </div>

      <div class="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
        <button type="button" class="text-xs text-slate-500 hover:text-slate-700" @click="clearRange">
          {{ t('results.filters.dateRangeClear') }}
        </button>
        <span class="text-xs text-slate-400">
          {{ tempStart ? `${tempStart}${tempEnd ? ' — ' + tempEnd : ''}` : t('results.filters.dateRangePickHint') }}
        </span>
      </div>
    </div>
  </div>
</template>
