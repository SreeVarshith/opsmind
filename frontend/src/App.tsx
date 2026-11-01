import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { clearSession, savedUser, setUnauthorizedHandler, type User } from "./lib/api";
import { AskPage } from "./pages/AskPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { MonitoringPage } from "./pages/MonitoringPage";

export function App() {
  const [user, setUser] = useState<User | null>(savedUser);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      setUser(null);
      setNotice("Your session expired. Log in again.");
    });
  }, []);

  if (!user) {
    return (
      <LoginPage
        notice={notice}
        onLogin={(u) => {
          setNotice(null);
          setUser(u);
        }}
      />
    );
  }

  const canManage = user.role === "admin" || user.role === "sre";
  return (
    <Layout
      user={user}
      canManage={canManage}
      onLogout={() => {
        clearSession();
        setUser(null);
      }}
    >
      <Routes>
        <Route path="/" element={<AskPage />} />
        <Route path="/history" element={<HistoryPage />} />
        {canManage && <Route path="/documents" element={<DocumentsPage />} />}
        {canManage && <Route path="/monitoring" element={<MonitoringPage />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
