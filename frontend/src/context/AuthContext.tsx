import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { login as loginRequest } from '../api/auth';

interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // Read from localStorage on mount so a page refresh doesn't boot the user
  // out — the token itself is still validated server-side on every request
  // via the 401 interceptor in api/client.ts.
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('access_token'));

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await loginRequest(username, password);
    localStorage.setItem('access_token', access_token);
    setToken(access_token);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, isAuthenticated: !!token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
