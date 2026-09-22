import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, getToken, setToken, setUnauthorizedHandler, type Me } from "./api";

interface AuthState {
  user: Me | null;
  loading: boolean;
  signIn: (slug: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  // A 401 from any request anywhere ends the session, so the UI never sits
  // in a state where it looks signed in but every call fails.
  useEffect(() => {
    setUnauthorizedHandler(signOut);
  }, [signOut]);

  // A stored token is not trusted on its own: it may be expired. /me is the
  // check, and it also gives us the tenant to display.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(
    async (slug: string, email: string, password: string) => {
      const { access_token } = await api.login(slug, email, password);
      setToken(access_token);
      setUser(await api.me());
    },
    [],
  );

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
