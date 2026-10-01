import React, { createContext, useContext, useState, useEffect } from "react";
import { Api, errorMessage } from "./api";
import { vault } from "./vault";
import { createDemo } from "./demo";
import type { Access, Role } from "./types";
const liveApi = () =>
  new Api(vault, process.env.EXPO_PUBLIC_API_URL || undefined);
type Context = {
  api: Api;
  access: Access | null;
  loading: boolean;
  error: string;
  demo: boolean;
  login: (id: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  preview: (role: Role) => Promise<void>;
  restore: () => Promise<void>;
};
const SessionContext = createContext<Context | null>(null);
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [api, setApi] = useState(liveApi);
  const [access, setAccess] = useState<Access | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState(false);
  useEffect(
    () =>
      api.subscribeExpired(() => {
        setAccess(null);
        setError("Your session expired. Please sign in again.");
      }),
    [api],
  );
  const restore = async () => {
    setLoading(true);
    setError("");
    try {
      setAccess(await api.restore());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    let active = true;
    api
      .restore()
      .then((value) => {
        if (active) setAccess(value);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api]);
  return (
    <SessionContext.Provider
      value={{
        api,
        access,
        loading,
        error,
        demo,
        restore,
        login: async (id, password) => {
          setError("");
          const next = demo ? liveApi() : api;
          const result = await next.login(id, password);
          setApi(next);
          setDemo(false);
          setAccess(result);
        },
        logout: async () => {
          setAccess(null);
          setError("");
          await api.logout();
          if (demo) {
            setApi(liveApi());
            setDemo(false);
          }
        },
        preview: async (role) => {
          const next = createDemo(role);
          const result = await next.login("demo", "demo");
          setApi(next);
          setDemo(true);
          setAccess(result);
        },
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("Session provider missing");
  return value;
}
