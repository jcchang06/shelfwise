import { apiGet, apiPost } from './client';
import { clearTokens, getRefreshToken, setAccessToken, setRefreshToken } from './tokens';

export interface User {
  id: number;
  email: string;
  date_joined: string;
}

interface TokenPair {
  access: string;
  refresh: string;
}

export async function login(email: string, password: string): Promise<void> {
  const tokens = await apiPost<TokenPair>('/auth/token/', { email, password }, { auth: false });
  setAccessToken(tokens.access);
  setRefreshToken(tokens.refresh);
}

export function fetchCurrentUser(): Promise<User> {
  return apiGet<User>('/auth/me/');
}

/** v1 has no server-side logout: forgetting the tokens ends the session on this device. */
export function logout(): void {
  clearTokens();
}

export function hasStoredSession(): boolean {
  return getRefreshToken() !== null;
}
