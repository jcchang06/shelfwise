import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { getStats } from '../api/stats';

export const statsKey = (year: number) => ['stats', year] as const;

/** Stats for a year. Keeps showing the previous year's charts while a new year loads
 * (no blank flash when switching years). */
export function useStats(year: number) {
  return useQuery({
    queryKey: statsKey(year),
    queryFn: () => getStats(year),
    placeholderData: keepPreviousData,
  });
}
