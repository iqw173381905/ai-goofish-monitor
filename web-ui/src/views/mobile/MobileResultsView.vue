<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RefreshCcw, ExternalLink, Star, Trash2 } from 'lucide-vue-next'
import { getResultFiles, getResultContent, deleteResultItem } from '@/api/results'
import { formatDateTime } from '@/i18n'
import { toast } from '@/components/ui/toast'
import type { ResultItem } from '@/types/result.d.ts'

const files = ref<string[]>([])
const items = ref<ResultItem[]>([])
const isLoading = ref(false)
const showRecommendedOnly = ref(true)

async function loadAll() {
  isLoading.value = true
  try {
    files.value = await getResultFiles()
    const all: ResultItem[] = []
    for (const f of files.value.slice(0, 10)) {
      try {
        // 推荐页用服务端过滤（和电脑端一致：ai + keyword 双通道）
        const params: any = { page: 1, limit: 50 }
        if (showRecommendedOnly.value) {
          params.ai_recommended_only = true
          params.keyword_recommended_only = true
        }
        const res: any = await getResultContent(f, params)
        const list = Array.isArray(res) ? res : (res.items || [])
        for (const it of list) (it as any)._sourceFile = f
        all.push(...list)
      } catch { /* 跳过失败的文件 */ }
    }
    // 按爬取时间倒序
    items.value = all.sort((a: any, b: any) =>
      String(b['爬取时间'] || '').localeCompare(String(a['爬取时间'] || '')))
  } finally {
    isLoading.value = false
  }
}

function switchTab(recommended: boolean) {
  if (showRecommendedOnly.value === recommended) return
  showRecommendedOnly.value = recommended
  loadAll()
}

function getInfo(it: any) {
  return it['商品信息'] || {}
}
function itemTitle(it: any) {
  return getInfo(it)['商品标题'] || '未知商品'
}
function itemPrice(it: any) {
  return getInfo(it)['当前售价'] || ''
}
function itemOriginalPrice(it: any) {
  const v = getInfo(it)['商品原价']
  if (!v || ['暂无', '-', 'N/A', '价格异常'].includes(String(v).trim())) return ''
  return v
}
// 桌面端链接转手机端：www.goofish.com → h5.m.goofish.com
function toMobileLink(url: string) {
  if (!url) return ''
  return url.replace('://www.goofish.com', '://h5.m.goofish.com')
}
function itemLink(it: any) {
  return toMobileLink(getInfo(it)['商品链接'] || '')
}
function itemImage(it: any) {
  const info = getInfo(it)
  return info['商品主图链接'] || (info['商品图片列表'] && info['商品图片列表'][0]) || ''
}
function isRecommended(it: any) {
  return it.ai_analysis?.is_recommended === true
}
function itemWant(it: any) {
  return getInfo(it)['“想要”人数'] || ''
}
function itemRegion(it: any) {
  return getInfo(it)['发货地区'] || ''
}
function itemCrawlTime(it: any) {
  const t = it['爬取时间']
  return t ? formatDateTime(t, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
}
function itemId(it: any) {
  return getInfo(it)['商品ID'] || ''
}
const deletingIdx = ref<number | null>(null)
async function handleDelete(it: any, idx: number) {
  const filename = (it as any)._sourceFile
  const id = itemId(it)
  if (!filename || !id) {
    toast({ title: '无法删除', description: '缺少文件或商品标识', variant: 'destructive' })
    return
  }
  if (!window.confirm(`确定删除「${itemTitle(it).slice(0, 20)}」吗？`)) return
  deletingIdx.value = idx
  try {
    await deleteResultItem(filename, id)
    items.value.splice(idx, 1)
    toast({ title: '已删除' })
  } catch (e) {
    toast({ title: '删除失败', description: (e as Error).message, variant: 'destructive' })
  } finally {
    deletingIdx.value = null
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="p-4">
    <!-- 筛选切换 -->
    <div class="flex gap-2 mb-4">
      <button
        type="button"
        class="flex-1 h-11 rounded-xl text-sm font-bold transition-colors"
        :class="showRecommendedOnly ? 'bg-primary text-white' : 'bg-white text-slate-500 border border-slate-200'"
        @click="switchTab(true)"
      >
        推荐商品
      </button>
      <button
        type="button"
        class="flex-1 h-11 rounded-xl text-sm font-bold transition-colors"
        :class="!showRecommendedOnly ? 'bg-primary text-white' : 'bg-white text-slate-500 border border-slate-200'"
        @click="switchTab(false)"
      >
        全部商品
      </button>
      <button
        type="button"
        class="w-11 h-11 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-slate-500 active:bg-slate-100"
        @click="loadAll"
        aria-label="刷新"
      >
        <RefreshCcw class="w-5 h-5" :class="isLoading && 'animate-spin'" />
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="isLoading && items.length === 0" class="flex flex-col items-center py-16 gap-3 text-slate-400">
      <RefreshCcw class="w-8 h-8 animate-spin" />
      <p class="text-sm">加载中…</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="items.length === 0" class="text-center py-16 text-slate-300">
      <p class="text-sm font-bold">{{ showRecommendedOnly ? '暂无推荐商品' : '暂无商品' }}</p>
      <p class="text-xs mt-1">任务运行后会自动分析推荐</p>
    </div>

    <!-- 商品列表 -->
    <div v-else class="space-y-3">
      <article
        v-for="(it, idx) in items"
        :key="idx"
        class="bg-white rounded-2xl border border-slate-200/60 overflow-hidden shadow-sm"
      >
        <div class="flex gap-3 p-3">
          <img
            v-if="itemImage(it)"
            :src="itemImage(it)"
            class="w-20 h-20 rounded-xl object-cover flex-shrink-0 bg-slate-100"
            loading="lazy"
            alt=""
          />
          <div class="flex-1 min-w-0">
            <h3 class="text-sm font-bold text-slate-800 line-clamp-2 leading-snug">
              {{ itemTitle(it) }}
            </h3>
            <div class="flex items-baseline gap-2 mt-1">
              <p class="text-base font-black text-rose-600">{{ itemPrice(it) }}</p>
              <p v-if="itemOriginalPrice(it)" class="text-xs text-slate-300 line-through">{{ itemOriginalPrice(it) }}</p>
            </div>
            <div class="flex items-center gap-2 mt-1 flex-wrap">
              <span
                v-if="isRecommended(it)"
                class="inline-flex items-center gap-0.5 text-[11px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded"
              >
                <Star class="w-3 h-3 fill-current" /> 推荐
              </span>
              <span v-if="itemWant(it)" class="text-[11px] text-slate-400">{{ itemWant(it) }}人想要</span>
              <span v-if="itemRegion(it)" class="text-[11px] text-slate-400">{{ itemRegion(it) }}</span>
              <span v-if="itemCrawlTime(it)" class="text-[11px] text-slate-400">{{ itemCrawlTime(it) }} 抓取</span>
            </div>
            <div class="flex items-center gap-2 mt-2">
              <a
                v-if="itemLink(it)"
                :href="itemLink(it)"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-xs font-bold text-primary bg-primary/10 px-3 py-1.5 rounded-lg active:bg-primary/20"
              >
                <ExternalLink class="w-3.5 h-3.5" /> 去闲鱼查看
              </a>
              <button
                type="button"
                :disabled="deletingIdx === idx"
                @click="handleDelete(it, idx)"
                class="inline-flex items-center gap-1 text-xs font-bold text-rose-500 bg-rose-50 px-3 py-1.5 rounded-lg active:bg-rose-100 disabled:opacity-50"
                aria-label="删除该商品"
              >
                <Trash2 class="w-3.5 h-3.5" /> {{ deletingIdx === idx ? '删除中…' : '删除' }}
              </button>
            </div>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
