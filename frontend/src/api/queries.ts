import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import type { FeedbackRequest, RecommendationRequest } from './types'

export const HISTORY_PAGE_SIZE = 20

const historyKey = ['history'] as const

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: api.meta,
    // The configuration only changes when the backend restarts.
    staleTime: Infinity,
  })
}

export function useTranscribe() {
  return useMutation({
    mutationFn: ({ audio, filename }: { audio: Blob; filename: string }) =>
      api.transcribe(audio, filename),
  })
}

export function useHistory(offset: number) {
  return useQuery({
    queryKey: [...historyKey, offset],
    queryFn: () => api.history(HISTORY_PAGE_SIZE, offset),
    // Keep the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  })
}

export function useRecommend() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: RecommendationRequest) => api.recommend(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: historyKey }),
  })
}

export function useAnswerClarification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, answer }: { requestId: string; answer: string }) =>
      api.answerClarification(requestId, answer),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: historyKey }),
  })
}

export function useSendFeedback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, ...body }: FeedbackRequest & { requestId: string }) =>
      api.sendFeedback(requestId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: historyKey }),
  })
}
