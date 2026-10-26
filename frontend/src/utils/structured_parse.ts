/**
 * 结构化回答的容错解析
 * ====================
 * 后端已经把模型输出规范化过一次，但前端仍然必须自己兜一层，原因：
 *   1. 网络/版本不一致时字段可能缺失
 *   2. 表格 rows 可能不齐、timeline 里可能混进非对象
 *   3. 组件渲染不能因为一个坏字段整页白屏
 *
 * 契约（与 backend/app/schemas/structured.py 保持一致）：
 *   bullets    { title, bullets: string[] }
 *   comparison { title, headers: string[], rows: string[][] }
 *   timeline   { title, events: { time, title, detail }[] }
 *
 * 本文件的函数都是纯函数 —— 没有 DOM、没有请求，所以可以直接用 vitest 测。
 */

export type AnswerTemplate = 'bullets' | 'comparison' | 'timeline'

export interface BulletsResult {
  template: 'bullets'
  title: string
  bullets: string[]
}

export interface ComparisonResult {
  template: 'comparison'
  title: string
  headers: string[]
  rows: string[][]
}

export interface TimelineEvent {
  time: string
  title: string
  detail: string
}

export interface TimelineResult {
  template: 'timeline'
  title: string
  events: TimelineEvent[]
}

export type StructuredResult = BulletsResult | ComparisonResult | TimelineResult

/** 后端 POST /api/structured/generate 的响应 */
export interface StructuredResponse {
  template: AnswerTemplate
  result: unknown
  raw: string
  degraded: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 列表类字段：转字符串 + 去空 */
function toTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (item === null || item === undefined ? '' : String(item).trim()))
    .filter((text) => text.length > 0)
}

/** 表格单元格：保留位置（空格子不能被过滤，否则列会错位） */
function toCellList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((cell) => (cell === null || cell === undefined ? '' : String(cell)))
}

/** 把一行补齐/截断到表头列数，保证渲染出来是矩形 */
function fitCells(cells: string[], width: number): string[] {
  if (width <= 0) return []
  const out = cells.slice(0, width)
  while (out.length < width) out.push('')
  return out
}

function emptyBullets(): BulletsResult {
  return { template: 'bullets', title: '', bullets: [] }
}

/**
 * 判断用哪个模板渲染。
 * 优先用后端声明的 template；缺失时按「像什么」猜（字段名是最可靠线索）。
 */
function resolveTemplate(
  payload: Record<string, unknown>,
  hint: unknown,
): AnswerTemplate {
  const declared = hint ?? payload.template
  if (declared === 'bullets' || declared === 'comparison' || declared === 'timeline') {
    return declared
  }
  if (Array.isArray(payload.headers) || Array.isArray(payload.rows)) return 'comparison'
  if (Array.isArray(payload.events)) return 'timeline'
  return 'bullets'
}

function normalizeBullets(payload: Record<string, unknown>): BulletsResult {
  const title = typeof payload.title === 'string' ? payload.title.trim() : ''
  return { template: 'bullets', title, bullets: toTextList(payload.bullets) }
}

function normalizeComparison(payload: Record<string, unknown>): StructuredResult {
  const title = typeof payload.title === 'string' ? payload.title.trim() : ''
  const headers = toTextList(payload.headers)
  const rawRows = Array.isArray(payload.rows) ? payload.rows : []

  const rows = rawRows
    .filter((row): row is unknown[] => Array.isArray(row))
    .map((row) => fitCells(toCellList(row), headers.length))
    .filter((row) => row.some((cell) => cell.length > 0))

  // 表头或数据缺失时退化为要点，而不是渲染一个空表
  if (headers.length === 0 || rows.length === 0) {
    return normalizeBullets(payload)
  }
  return { template: 'comparison', title, headers, rows }
}

function normalizeTimeline(payload: Record<string, unknown>): StructuredResult {
  const title = typeof payload.title === 'string' ? payload.title.trim() : ''
  const rawEvents = Array.isArray(payload.events) ? payload.events : []

  const events: TimelineEvent[] = rawEvents
    .filter(isRecord)
    .map((event) => ({
      time: event.time === undefined || event.time === null ? '' : String(event.time),
      title: event.title === undefined || event.title === null ? '' : String(event.title),
      detail: event.detail === undefined || event.detail === null ? '' : String(event.detail),
    }))
    .filter((event) => event.title.length > 0 || event.detail.length > 0)

  if (events.length === 0) {
    return normalizeBullets(payload)
  }
  return { template: 'timeline', title, events }
}

/**
 * 统一入口：接受三种输入都能得到可渲染结果
 *   - null / undefined / 字符串          -> 空要点
 *   - 后端完整响应 { template, result }  -> 取 result 并按 template 渲染
 *   - 裸 result 对象                     -> 按字段猜模板
 */
export function normalizeStructured(input: unknown): StructuredResult {
  if (!isRecord(input)) return emptyBullets()

  // 兼容后端完整响应：{ template, result, degraded, raw }
  const payload = isRecord(input.result) ? input.result : input
  const template = resolveTemplate(payload, input.template)

  if (template === 'comparison') return normalizeComparison(payload)
  if (template === 'timeline') return normalizeTimeline(payload)
  return normalizeBullets(payload)
}
