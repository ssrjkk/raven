import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "./design/ThemeContext";
import Layout from "./components/Layout";
import Chat from "./components/Chat";
import Admin from "./pages/Admin";
import Dashboard from "./pages/Dashboard";
import Tasks from "./pages/Tasks";
import Monitors from "./pages/Monitors";
import Routines from "./pages/Routines";
import Workflows from "./pages/Workflows";
import CodeSessions from "./pages/CodeSessions";
import Settings from "./pages/Settings";
import IDEPage from "./pages/IDE";
import Git from "./pages/Git";
import GitHub from "./pages/GitHub";
import CICD from "./pages/CICD";
import Tests from "./pages/Tests";
import Media from "./pages/Media";
import Knowledge from "./pages/Knowledge";
import ABTesting from "./pages/ABTesting";
import Analytics from "./pages/Analytics";
import CostManagement from "./pages/CostManagement";
import Voice from "./pages/Voice";
import Collab from "./pages/Collab";
import RAG from "./pages/RAG";
import FineTune from "./pages/FineTune";
import Chaos from "./pages/Chaos";
import EmailPage from "./pages/Email";
import Browser from "./pages/Browser";
import WebSearch from "./pages/WebSearch";
import Plugins from "./pages/Plugins";
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
            <Route path="workflows" element={<Workflows />} />
            <Route path="monitors" element={<Monitors />} />
            <Route path="routines" element={<Routines />} />
            <Route path="code" element={<CodeSessions />} />
            <Route path="ide" element={<IDEPage />} />
            <Route path="git" element={<Git />} />
            <Route path="github" element={<GitHub />} />
            <Route path="cicd" element={<CICD />} />
            <Route path="tests" element={<Tests />} />
            <Route path="media" element={<Media />} />
            <Route path="knowledge" element={<Knowledge />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="abtesting" element={<ABTesting />} />
            <Route path="cost" element={<CostManagement />} />
            <Route path="voice" element={<Voice />} />
            <Route path="collab" element={<Collab />} />
            <Route path="rag" element={<RAG />} />
            <Route path="finetune" element={<FineTune />} />
            <Route path="chaos" element={<Chaos />} />
            <Route path="email" element={<EmailPage />} />
            <Route path="browser" element={<Browser />} />
            <Route path="web-search" element={<WebSearch />} />
            <Route path="plugins" element={<Plugins />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}