/**
 * structured_parse 的纯函数测试
 * 运行：npm run test（或 npx vitest run）
 *
 * 说明：这里只测「确定输入 → 确定输出」，不需要 DOM、不需要 mock 网络。
 * 学习重点：测错误输入比测正确输入更有价值 —— 线上崩的从来不是标准用例。
 */
import { describe, expect, it } from 'vitest'
import { normalizeStructured } from '../src/utils/structured_parse'

describe('normalizeStructured', () => {
  it('空输入返回空要点，不抛异常', () => {
    const result = normalizeStructured(null)
    expect(result.template).toBe('bullets')
    if (result.template !== 'bullets') throw new Error('类型收窄失败')
    expect(result.bullets).toEqual([])
  })

  it('识别后端完整响应里的 bullets', () => {
    const result = normalizeStructured({
      template: 'bullets',
      result: { title: '退款周期', bullets: ['1-3 个工作日', '  ', '原路退回'] },
      degraded: false,
    })
    expect(result.template).toBe('bullets')
    if (result.template !== 'bullets') throw new Error('类型收窄失败')
    // 空字符串要被过滤掉
    expect(result.bullets).toEqual(['1-3 个工作日', '原路退回'])
  })

  it('comparison 的行长度与表头对齐（短的补空、长的截断）', () => {
    const result = normalizeStructured({
      template: 'comparison',
      headers: ['维度', '方案A', '方案B'],
      rows: [['价格', '12 元'], ['周期', '1 天', '3 天', '多出来的列']],
    })
    if (result.template !== 'comparison') throw new Error('类型收窄失败')
    expect(result.headers).toEqual(['维度', '方案A', '方案B'])
    expect(result.rows).toEqual([
      ['价格', '12 元', ''],
      ['周期', '1 天', '3 天'],
    ])
  })

  it('timeline 丢弃非对象事件，并按字段缺失补空串', () => {
    const result = normalizeStructured({
      template: 'timeline',
      events: [
        { time: '2024-01', title: '立项' },
        '脏数据',
        null,
        { detail: '只有描述' },
      ],
    })
    if (result.template !== 'timeline') throw new Error('类型收窄失败')
    expect(result.events).toEqual([
      { time: '2024-01', title: '立项', detail: '' },
      { time: '', title: '', detail: '只有描述' },
    ])
  })

  it('未知模板但有 bullets 时回退为要点列表', () => {
    const result = normalizeStructured({
      template: 'mindmap',
      title: '兜底',
      bullets: ['要点一'],
    })
    expect(result.template).toBe('bullets')
    if (result.template !== 'bullets') throw new Error('类型收窄失败')
    expect(result.title).toBe('兜底')
    expect(result.bullets).toEqual(['要点一'])
  })
})
