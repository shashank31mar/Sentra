import { describe, it, expect, beforeEach } from 'vitest'
import {
  getActiveTenant,
  setActiveTenant,
  clearActiveTenant,
  tenantHeader,
} from '../tenant'

const KEY = 'aegion.activeTenant'

describe('active-tenant binding — per-tab sessionStorage (G2.11 / ADR-039)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
    clearActiveTenant()
  })

  it('setActiveTenant writes to sessionStorage (NOT localStorage)', () => {
    setActiveTenant('t_globex')
    expect(window.sessionStorage.getItem(KEY)).toBe('t_globex')
    expect(window.localStorage.getItem(KEY)).toBeNull()
    expect(getActiveTenant()).toBe('t_globex')
    expect(tenantHeader()).toEqual({ 'X-Aegion-Tenant': 't_globex' })
  })

  it('clearActiveTenant empties the binding and the header', () => {
    setActiveTenant('t_globex')
    clearActiveTenant()
    expect(window.sessionStorage.getItem(KEY)).toBeNull()
    expect(getActiveTenant()).toBeNull()
    expect(tenantHeader()).toEqual({})
  })

  it('setActiveTenant(null) omits the header', () => {
    setActiveTenant(null)
    expect(tenantHeader()).toEqual({})
  })
})
