import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { loginUser, registerUser, getMe, logoutUser } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => {
    try {
      return localStorage.getItem('token') || null;
    } catch {
      return null;
    }
  });

  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Validate existing token on mount
  useEffect(() => {
    let isMounted = true;
    let retryTimer = null;

    async function loadUser() {
      if (!token) {
        if (isMounted) setLoading(false);
        return;
      }
      try {
        const res = await getMe();
        if (isMounted) {
          setUser(res.data);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          const status = err?.response?.status;
          if (status === 401 || status === 403) {
            // Token genuinely rejected (expired / user deleted) -> sign out
            console.warn('Session expired or invalid token:', err);
            try {
              localStorage.removeItem('token');
            } catch {}
            setToken(null);
            setUser(null);
          } else {
            // Server asleep (Render cold start), network blip, 5xx: keep the session and retry
            console.warn('Could not verify session right now, will retry:', err?.message);
            retryTimer = setTimeout(loadUser, 4000);
          }
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadUser();
    return () => {
      isMounted = false;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [token]);

  const login = useCallback(async (credentialsOrSession) => {
    setError(null);
    try {
      let data;
      // Handle either raw credentials or pre-resolved session payload (e.g. Google OAuth)
      if (credentialsOrSession?.access_token && credentialsOrSession?.user) {
        data = credentialsOrSession;
      } else {
        const res = await loginUser(credentialsOrSession);
        data = res.data;
      }
      const { access_token, user: userData } = data;
      try {
        localStorage.setItem('token', access_token);
      } catch {}
      setToken(access_token);
      setUser(userData);
      return data;
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Login failed';
      setError(message);
      throw new Error(message);
    }
  }, []);

  const register = useCallback(async (data) => {
    setError(null);
    try {
      const res = await registerUser(data);
      const { access_token, user: userData } = res.data;
      try {
        localStorage.setItem('token', access_token);
      } catch {}
      setToken(access_token);
      setUser(userData);
      return res.data;
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Registration failed';
      setError(message);
      throw new Error(message);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutUser().catch(() => {});
    } finally {
      try {
        localStorage.removeItem('token');
      } catch {}
      setToken(null);
      setUser(null);
      setError(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        loading,
        error,
        isAuthenticated: !!token && !!user,
        login,
        register,
        logout,
        setError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default AuthContext;
