<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { RefreshCcw, ExternalLink, Star } from 'lucide-vue-next'
import { getResultFiles, getResultContent } from '@/api/results'
import type { ResultItem } from '@/types/result.d.ts'

const files = ref<string[]>([])
const items = ref<ResultItem[]>([])
const isLoading = ref(false)
const showRecommendedOnly = ref(true)

const filteredItems = computed(() => {
  if (!showRecommendedOnly.value) return items.value
  return items.value.filter((it: any) => it.is_recommended || it['是否推荐'] === '是')
})

async function loadAll() {
  isLoading.value = true
  try {
    files.value = await getResultFiles()
    const all: ResultItem[] = []
    for (const f of files.value.slice(0, 10)) {
      try {
        const res: any = await getResultContent(f, { page: 1, limit: 50 } as any)
        const list = Array.isArray(res) ? res : (res.items || [])
        all.push(...list)
      } catch { /* 跳过失败的文件 */ }
    }
    // 按爬取时间倒序
    items.value = all.sort((a: any, b: any) =>
      String(b.crawl_time || b['爬取时间'] || '').localeCompare(String(a.crawl_time || a['爬取时间'] || ''))
    )
  } finally {
    isLoading.value = false
  }
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
function itemLink(it: any) {
  return getInfo(it)['商品链接'] || ''
}
function itemImage(it: any) {
  const info = getInfo(it)
  return info['商品主图链接'] || (info['商品图片列表'] && info['商品图片列表'][0]) || ''
}
function isRecommended(it: any) {
  return it.ai_analysis?.is_recommended === true
}

onMounted(loadAll)
</script>

<template>
  <div class="p-4">
    <!-- 筛选切换 -->
    <div class="flex gap-2 mb-4">
      <button
        type="button"
        class="flex-1 h-10 rounded-xl text-sm font-bold transition-colors"
        :class="showRecommendedOnly ? 'bg-primary text-white' : 'bg-white text-slate-500 border border-slate-200'"
        @click="showRecommendedOnly = true"
      >
        推荐商品
      </button>
      <button
        type="button"
        class="flex-1 h-10 rounded-xl text-sm font-bold transition-colors"
        :class="!showRecommendedOnly ? 'bg-primary text-white' : 'bg-white text-slate-500 border border-slate-200'"
        @click="showRecommendedOnly = false"
      >
        全部商品
      </button>
      <button
        type="button"
        class="w-10 h-10 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-slate-500 active:bg-slate-100"
        @click="loadAll"
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
    <div v-else-if="filteredItems.length === 0" class="text-center py-16 text-slate-300">
      <p class="text-sm font-bold">暂无商品</p>
    </div>

    <!-- 商品列表 -->
    <div v-else class="space-y-3">
      <article
        v-for="(it, idx) in filteredItems"
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
            <p class="text-base font-black text-rose-600 mt-1">{{ itemPrice(it) }}</p>
            <div class="flex items-center gap-2 mt-1">
              <span
                v-if="isRecommended(it)"
                class="inline-flex items-center gap-0.5 text-[11px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded"
              >
                <Star class="w-3 h-3 fill-current" /> 推荐
              </span>
              <a
                v-if="itemLink(it)"
                :href="itemLink(it)"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-0.5 text-[11px] font-bold text-primary"
              >
                <ExternalLink class="w-3 h-3" /> 查看详情
              </a>
            </div>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
