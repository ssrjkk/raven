import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

export function useApiQuery<T>(
  key: string[],
  fetcher: () => Promise<T>,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
) {
  return useQuery<T>({ queryKey: key, queryFn: fetcher, ...options });
}
