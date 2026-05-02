import { useCallback, useState } from "react";
import App from "./App";
import Login from "./Login";
import { clearToken, getToken } from "./auth";

export default function Root() {
  const [token, setTok] = useState<string | null>(() => getToken());

  const onLoggedIn = useCallback(() => {
    setTok(getToken());
  }, []);

  const onLogout = useCallback(() => {
    clearToken();
    setTok(null);
  }, []);

  if (!token) {
    return <Login onLoggedIn={onLoggedIn} />;
  }

  return <App onLogout={onLogout} />;
}
