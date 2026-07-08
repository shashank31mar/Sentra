import { http } from '../http'
import type { UsageRollup } from '../../types/api'

/** Metered usage rollup (`GET /v1/usage`, WS-H). Returns 404/501 until WS-H ships. */
export const usageApi = {
  get: () => http.get<UsageRollup>('/usage'),
}
