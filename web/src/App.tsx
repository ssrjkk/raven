import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "./design/ThemeContext";
import Layout from "./components/Layout";
import Chat from "./components/Chat";
import Admin from "./pages/Admin";
import Dashboard from "./pages/Dashboard";
import Tasks from "./pages/Tasks";
import Monitors from "./pages/Monitors";
import Routines from "./pages/Routines";
import CodeSessions from "./pages/CodeSessions";
import Settings from "./pages/Settings";
import IDEPage from "./pages/IDE";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import { isAuthenticated } from "./api/client";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="chat" element={<Chat />} />
            <Route path="admin" element={<Admin />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="monitors" element={<Monitors />} />
            <Route path="routines" element={<Routines />} />
            <Route path="code" element={<CodeSessions />} />
            <Route path="ide" element={<IDEPage />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}