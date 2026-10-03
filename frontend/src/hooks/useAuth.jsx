import { useState, useEffect, createContext, useContext } from 'react';
import { authAPI } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      authAPI.getMe()
        .then(res => setUser(res.data))
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  // Store a freshly issued token and load the profile it belongs to.
  const loginWithToken = async (token) => {
    localStorage.setItem('token', token);
    try {
      const userRes = await authAPI.getMe();
      setUser(userRes.data);
      return userRes.data;
    } catch (err) {
      localStorage.removeItem('token');
      throw err;
    }
  };

  const login = async (email, password) => {
    const res = await authAPI.login({ email, password });
    return loginWithToken(res.data.access_token);
  };

  /**
   * Returns the signed-in user, or — when the server requires email
   * verification — { verificationRequired: true, email, message, ticket } and no session.
   */
  const register = async (email, password, full_name) => {
    const res = await authAPI.register({ email, password, full_name });
    if (res.data.verification_required) {
      const { email: to, message, verification_ticket: ticket } = res.data;
      return { verificationRequired: true, email: to, message, ticket };
    }
    return loginWithToken(res.data.access_token);
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, loginWithToken, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
