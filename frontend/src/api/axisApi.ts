import client from './client'
import type {
  Axis1RunRequest, Axis1RunResponse,
  Axis2RunRequest, Axis2RunResponse,
  Axis3RunRequest, Axis3RunResponse,
} from '../types'

export async function runAxis1(params: Axis1RunRequest): Promise<Axis1RunResponse> {
  const { data } = await client.post<Axis1RunResponse>('/tools/axis1/run', params)
  return data
}

export async function runAxis2(params: Axis2RunRequest): Promise<Axis2RunResponse> {
  const { data } = await client.post<Axis2RunResponse>('/tools/axis2/run', params)
  return data
}

export async function runAxis3(params: Axis3RunRequest): Promise<Axis3RunResponse> {
  const { data } = await client.post<Axis3RunResponse>('/tools/axis3/run', params)
  return data
}
