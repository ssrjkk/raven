import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect,useState } from "react";
import { BrowserRouter, Navigate,Route, Routes } from "react-router-dom";

import { isAuthenticated } from "./api/client";
import Chat from "./components/Chat";
import { CommandPalette } from "./components/CommandPalette";
import Layout from "./components/Layout";
import { ThemeProvider } from "./design/ThemeContext";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000, refetchOnWindowFocus: false } },
});

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const [isCmdKOpen, setIsCmdKOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setIsCmdKOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <CommandPalette
        isOpen={isCmdKOpen}
        onClose={() => setIsCmdKOpen(false)}
      />
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
            <Route path="chat/history" element={<ChatHistory />} />
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
            <Route path="insights" element={<Insights />} />
            <Route path="project-insights" element={<ProjectInsights />} />
            <Route path="components" element={<ComponentLibrary />} />
            <Route path="scaffold" element={<Scaffold />} />
            <Route path="code-quality" element={<CodeQuality />} />
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
            <Route path="dream" element={<Dream />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
    </QueryClientProvider>
  );
}

// Lazy-loaded pages
import { lazy } from "react";
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Admin = lazy(() => import("./pages/Admin"));
const Tasks = lazy(() => import("./pages/Tasks"));
const Monitors = lazy(() => import("./pages/Monitors"));
const Routines = lazy(() => import("./pages/Routines"));
const Workflows = lazy(() => import("./pages/Workflows"));
const CodeSessions = lazy(() => import("./pages/CodeSessions"));
const IDEPage = lazy(() => import("./pages/IDE"));
const Git = lazy(() => import("./pages/Git"));
const GitHub = lazy(() => import("./pages/GitHub"));
const CICD = lazy(() => import("./pages/CICD"));
const Tests = lazy(() => import("./pages/Tests"));
const Media = lazy(() => import("./pages/Media"));
const Knowledge = lazy(() => import("./pages/Knowledge"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Insights = lazy(() => import("./pages/Insights"));
const ProjectInsights = lazy(() => import("./pages/ProjectInsights"));
const ComponentLibrary = lazy(() => import("./pages/ComponentLibrary"));
const Scaffold = lazy(() => import("./pages/Scaffold"));
const CodeQuality = lazy(() => import("./pages/CodeQuality"));
const ABTesting = lazy(() => import("./pages/ABTesting"));
const CostManagement = lazy(() => import("./pages/CostManagement"));
const Voice = lazy(() => import("./pages/Voice"));
const Collab = lazy(() => import("./pages/Collab"));
const RAG = lazy(() => import("./pages/RAG"));
const FineTune = lazy(() => import("./pages/FineTune"));
const Chaos = lazy(() => import("./pages/Chaos"));
const EmailPage = lazy(() => import("./pages/Email"));
const Browser = lazy(() => import("./pages/Browser"));
const WebSearch = lazy(() => import("./pages/WebSearch"));
const Plugins = lazy(() => import("./pages/Plugins"));
const ChatHistory = lazy(() => import("./pages/ChatHistory"));
const Dream = lazy(() => import("./pages/Dream"));
const Settings = lazy(() => import("./pages/Settings"));
