import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  api,
  getToken,
  setToken,
  setUnauthorizedHandler,
  type Me,
} from "./api";

interface AuthState {
  user: Me | null;
  loading: boolean;
  /** The stored session could not be confirmed yet, but has not been rejected
   *  either. The UI stays usable and says so rather than pretending. */
  reconnecting: boolean;
  signIn: (slug: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const CACHE_KEY = "dispatchledger.me";

/**
 * The last confirmed identity, kept beside the token.
 *
 * Not a security boundary and not treated as one: every request still carries
 * the token, and the server decides what it may read. This only spares the
 * person a blank screen on reload while /me is in flight, and gives the app
 * something to show when the server is slow to wake.
 */
function readCachedUser(): Me | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as Me) : null;
  } catch {
    return null;
  }
}

function writeCachedUser(user: Me | null) {
  try {
    if (user) localStorage.setItem(CACHE_KEY, JSON.stringify(user));
    else localStorage.removeItem(CACHE_KEY);
  } catch {
    // Private browsing, or storage full. The app works without the cache.
  }
}

const RETRY_DELAYS_MS = [2_000, 5_000, 12_000, 20_000];

export function AuthProvider({ children }: { children: ReactNode }) {
  // Start from the cached identity when a token is present, so a reload
  // paints the application immediately instead of a spinner.
  const [user, setUser] = useState<Me | null>(() =>
    getToken() ? readCachedUser() : null,
  );
  const [loading, setLoading] = useState(() => Boolean(getToken()) && !user);
  const [reconnecting, setReconnecting] = useState(false);
  const cancelled = useRef(false);

  const signOut = useCallback(() => {
    setToken(null);
    writeCachedUser(null);
    setUser(null);
    setReconnecting(false);
  }, []);

  // A 401 from any request anywhere ends the session, so the UI never sits
  // in a state where it looks signed in but every call fails.
  useEffect(() => {
    setUnauthorizedHandler(signOut);
  }, [signOut]);

  /**
   * Confirm the stored token, and keep trying if the server is simply absent.
   *
   * The distinction this makes is the whole point. A 401 means the server
   * looked at the token and refused it: the session is over, and the handler
   * above has already cleared it. Anything else -- a timeout, a dropped
   * connection, a 502 from a platform still starting a container -- means the
   * question was never answered. Throwing the session away on those is what
   * made a reload after an idle hour look like being logged out, and the
   * token was valid the whole time.
   */
  useEffect(() => {
    cancelled.current = false;
    if (!getToken()) {
      setLoading(false);
      return;
    }

    let attempt = 0;

    async function confirm() {
      try {
        const me = await api.me();
        if (cancelled.current) return;
        setUser(me);
        writeCachedUser(me);
        setReconnecting(false);
        setLoading(false);
      } catch (err) {
        if (cancelled.current) return;

        // 401 already triggered signOut through the handler.
        if (err instanceof ApiError && err.status === 401) {
          setLoading(false);
          return;
        }

        setReconnecting(true);
        setLoading(false);

        const delay = RETRY_DELAYS_MS[attempt];
        if (delay === undefined) return;
        attempt += 1;
        window.setTimeout(() => {
          if (!cancelled.current) void confirm();
        }, delay);
      }
    }

    void confirm();
    return () => {
      cancelled.current = true;
    };
  }, []);

  const signIn = useCallback(
    async (slug: string, email: string, password: string) => {
      const { access_token } = await api.login(slug, email, password);
      setToken(access_token);
      const me = await api.me();
      setUser(me);
      writeCachedUser(me);
      setReconnecting(false);
    },
    [],
  );

  const value = useMemo(
    () => ({ user, loading, reconnecting, signIn, signOut }),
    [user, loading, reconnecting, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
