import { useCallback, useState } from "react";
import { clearUserId, getUserId, setUserId } from "../lib/identity";

export function useAuth() {
  const [userId, setId] = useState<string>(() => getUserId());

  const login = useCallback((name: string) => {
    const v = name.trim();
    if (!v) return;
    setUserId(v);
    setId(v);
  }, []);

  const logout = useCallback(() => {
    clearUserId();
    setId("");
  }, []);

  return { userId, isAuthed: !!userId, login, logout };
}
